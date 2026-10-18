import * as anchor from "@anchor-lang/core";
import { BN, Program } from "@anchor-lang/core";
import { Keypair, LAMPORTS_PER_SOL, PublicKey } from "@solana/web3.js";
import { assert } from "chai";
import { createHash, randomBytes } from "crypto";
import type { Proofsettle } from "../target/types/proofsettle";

// Demo scenario from the PRD: 100 components, $10,000 invoice, $100 credit per
// confirmed defect, 3 defects -> $300 proposed adjustment. All amounts in cents.

describe("proofsettle", () => {
  const provider = anchor.AnchorProvider.env();
  anchor.setProvider(provider);
  const program = anchor.workspace.proofsettle as Program<Proofsettle>;

  // ---- helpers -----------------------------------------------------------

  const cents = (usd: number) => new BN(usd * 100);

  const sha256 = (data: string | Buffer): number[] =>
    Array.from(createHash("sha256").update(data).digest());

  const shipmentPda = (id: Buffer) =>
    PublicKey.findProgramAddressSync([Buffer.from("shipment"), id], program.programId)[0];

  const evidencePda = (shipment: PublicKey, index: number) => {
    const idx = Buffer.alloc(2);
    idx.writeUInt16LE(index);
    return PublicKey.findProgramAddressSync(
      [Buffer.from("evidence"), shipment.toBuffer(), idx],
      program.programId,
    )[0];
  };

  async function fund(...keypairs: Keypair[]) {
    for (const kp of keypairs) {
      const sig = await provider.connection.requestAirdrop(kp.publicKey, 5 * LAMPORTS_PER_SOL);
      await provider.connection.confirmTransaction(sig, "confirmed");
    }
  }

  async function expectFail(promise: Promise<unknown>, errorName: string) {
    try {
      await promise;
    } catch (e: unknown) {
      assert.include(String(e), errorName);
      return;
    }
    assert.fail(`expected failure with ${errorName}`);
  }

  interface Deal {
    buyer: Keypair;
    supplier: Keypair;
    authority: Keypair;
    reviewer: Keypair;
    shipment: PublicKey;
    termsHash: number[];
  }

  interface Rule {
    toleranceUnits?: number;
    minDispatch?: number;
    minReceipt?: number;
  }

  /** Creates a shipment in Draft. */
  async function createDeal(rule: Rule = {}): Promise<Deal> {
    const buyer = Keypair.generate();
    const supplier = Keypair.generate();
    const authority = Keypair.generate();
    const reviewer = Keypair.generate();
    await fund(buyer, supplier, authority, reviewer);

    const shipmentId = randomBytes(16);
    const shipment = shipmentPda(shipmentId);
    const termsHash = sha256(`terms-json-v1:${shipmentId.toString("hex")}`);

    await program.methods
      .createShipment(Array.from(shipmentId), {
        supplier: supplier.publicKey,
        authority: authority.publicKey,
        reviewer: reviewer.publicKey,
        termsHash,
        invoiceAmountCents: cents(10_000),
        quantity: 100,
        creditPerDefectCents: cents(100),
        maxAdjustmentCents: cents(5_000),
        defectToleranceUnits: rule.toleranceUnits ?? 0,
        minDispatchEvidence: rule.minDispatch ?? 1,
        minReceiptEvidence: rule.minReceipt ?? 1,
      })
      .accountsPartial({ shipment, buyer: buyer.publicKey })
      .signers([buyer])
      .rpc();

    return { buyer, supplier, authority, reviewer, shipment, termsHash };
  }

  const approve = (d: Deal, who: Keypair, hash: number[] = d.termsHash) =>
    program.methods
      .approveAgreement(hash)
      .accountsPartial({ shipment: d.shipment, party: who.publicKey })
      .signers([who])
      .rpc();

  async function newAgreedDeal(rule: Rule = {}): Promise<Deal> {
    const d = await createDeal(rule);
    await approve(d, d.buyer);
    await approve(d, d.supplier);
    return d;
  }

  async function recordEvidence(
    d: Deal,
    who: Keypair,
    kind: { dispatch: Record<string, never> } | { receipt: Record<string, never> },
    bytes: Buffer,
  ) {
    const s = await program.account.shipment.fetch(d.shipment);
    const evidence = evidencePda(d.shipment, s.evidenceCount);
    await program.methods
      .recordEvidence(kind, sha256(bytes))
      .accountsPartial({ shipment: d.shipment, evidence, uploader: who.publicKey })
      .signers([who])
      .rpc();
    return evidence;
  }

  const markInTransit = (d: Deal, who: Keypair = d.supplier) =>
    program.methods
      .markInTransit()
      .accountsPartial({ shipment: d.shipment, supplier: who.publicKey })
      .signers([who])
      .rpc();

  /** Agreed -> dispatch photo -> InTransit -> receipt photo -> Inspection. */
  async function dealInInspection(rule: Rule = {}): Promise<Deal> {
    const d = await newAgreedDeal(rule);
    await recordEvidence(d, d.supplier, { dispatch: {} }, Buffer.from("dispatch-photo-1"));
    await markInTransit(d);
    await recordEvidence(d, d.buyer, { receipt: {} }, Buffer.from("receipt-photo-1"));
    return d;
  }

  const propose = (d: Deal, defects: number, who: Keypair = d.authority) =>
    program.methods
      .proposeAdjustment(defects, sha256("findings-json"), sha256("adjustment-json"))
      .accountsPartial({ shipment: d.shipment, authority: who.publicKey })
      .signers([who])
      .rpc();

  const accept = (d: Deal, who: Keypair) =>
    program.methods
      .acceptAdjustment()
      .accountsPartial({ shipment: d.shipment, party: who.publicKey })
      .signers([who])
      .rpc();

  const dispute = (d: Deal, who: Keypair, reason = "damage happened in transit") =>
    program.methods
      .disputeAdjustment(sha256(reason))
      .accountsPartial({ shipment: d.shipment, party: who.publicKey })
      .signers([who])
      .rpc();

  const resolve = (d: Deal, defects: number, who: Keypair = d.reviewer) =>
    program.methods
      .resolveDispute(defects, sha256("resolved-adjustment-json"))
      .accountsPartial({ shipment: d.shipment, reviewer: who.publicKey })
      .signers([who])
      .rpc();

  const fetch = (d: Deal) => program.account.shipment.fetch(d.shipment);

  // ---- demo cases --------------------------------------------------------

  it("Case A: 3 defects x $100 -> $300 proposal, accepted only once both parties accept", async () => {
    const d = await dealInInspection();

    await propose(d, 3);
    let s = await fetch(d);
    assert.deepEqual(s.status, { proposed: {} });
    assert.equal(s.confirmedDefects, 3);
    assert.equal(s.proposedAdjustmentCents.toNumber(), 30_000);

    await accept(d, d.supplier);
    s = await fetch(d);
    assert.deepEqual(s.status, { proposed: {} }, "one acceptance is not enough");
    assert.isTrue(s.supplierAccepted);
    assert.isFalse(s.buyerAccepted);

    await accept(d, d.buyer);
    s = await fetch(d);
    assert.deepEqual(s.status, { accepted: {} });
    assert.equal(s.finalAdjustmentCents.toNumber(), 30_000);
    // created, 2 approvals, dispatch evidence, in transit, receipt evidence, proposed, 2 accepts
    assert.equal(s.auditSeq.toNumber(), 9);
  });

  it("Case B: the buyer disputes, only the reviewer resolves, and the amount comes from the rule", async () => {
    const d = await dealInInspection();
    await propose(d, 3);
    await dispute(d, d.buyer);

    let s = await fetch(d);
    assert.deepEqual(s.status, { disputed: {} });

    // Neither party, nor the rules engine, can resolve.
    await expectFail(resolve(d, 0, d.supplier), "Unauthorized");
    await expectFail(resolve(d, 0, d.buyer), "Unauthorized");
    await expectFail(resolve(d, 0, d.authority), "Unauthorized");

    // The reviewer confirms 2 of the 3 findings: 2 x $100.
    await resolve(d, 2);
    s = await fetch(d);
    assert.deepEqual(s.status, { resolved: {} });
    assert.equal(s.confirmedDefects, 2);
    assert.equal(s.finalAdjustmentCents.toNumber(), 20_000);
    assert.equal(s.auditSeq.toNumber(), 9);
  });

  it("the supplier can dispute too", async () => {
    const d = await dealInInspection();
    await propose(d, 3);
    await dispute(d, d.supplier);
    assert.deepEqual((await fetch(d)).status, { disputed: {} });
  });

  // ---- rules and guards --------------------------------------------------

  it("subtracts the defect tolerance before applying the credit", async () => {
    const d = await dealInInspection({ toleranceUnits: 1 });
    await propose(d, 3); // (3 - 1) x $100
    assert.equal((await fetch(d)).proposedAdjustmentCents.toNumber(), 20_000);
  });

  it("proposes nothing when the defects are within tolerance", async () => {
    const d = await dealInInspection({ toleranceUnits: 5 });
    await propose(d, 3);
    assert.equal((await fetch(d)).proposedAdjustmentCents.toNumber(), 0);
  });

  it("applies the same rule, tolerance included, when resolving", async () => {
    const d = await dealInInspection({ toleranceUnits: 1 });
    await propose(d, 3);
    await dispute(d, d.supplier);
    await resolve(d, 2); // (2 - 1) x $100
    assert.equal((await fetch(d)).finalAdjustmentCents.toNumber(), 10_000);
  });

  it("caps the proposal at the agreed maximum", async () => {
    const d = await dealInInspection();
    await propose(d, 60); // 60 x $100 = $6,000 > $5,000 cap
    assert.equal((await fetch(d)).proposedAdjustmentCents.toNumber(), 500_000);
  });

  it("rejects more defects than the shipment quantity", async () => {
    const d = await dealInInspection();
    await expectFail(propose(d, 101), "DefectsExceedQuantity");
  });

  it("only the authority can propose an adjustment", async () => {
    const d = await dealInInspection();
    await expectFail(propose(d, 3, d.supplier), "Unauthorized");
    await expectFail(propose(d, 3, d.reviewer), "Unauthorized");
  });

  it("a party can accept only once, and can't dispute after accepting", async () => {
    const d = await dealInInspection();
    await propose(d, 3);
    await accept(d, d.buyer);
    await expectFail(accept(d, d.buyer), "AlreadyAccepted");
    await expectFail(dispute(d, d.buyer), "AlreadyAccepted");
    // The other party can still dispute.
    await dispute(d, d.supplier);
    assert.deepEqual((await fetch(d)).status, { disputed: {} });
  });

  it("only the buyer or supplier can accept or dispute", async () => {
    const d = await dealInInspection();
    await propose(d, 3);
    await expectFail(accept(d, d.authority), "Unauthorized");
    await expectFail(dispute(d, d.reviewer), "Unauthorized");
  });

  it("needs the agreed number of dispatch photos before going in transit", async () => {
    const d = await newAgreedDeal({ minDispatch: 2 });
    await recordEvidence(d, d.supplier, { dispatch: {} }, Buffer.from("dispatch-1"));
    await expectFail(markInTransit(d), "MissingDispatchEvidence");
    await recordEvidence(d, d.supplier, { dispatch: {} }, Buffer.from("dispatch-2"));
    await markInTransit(d);
    assert.deepEqual((await fetch(d)).status, { inTransit: {} });
  });

  it("moves to Inspection only once the agreed number of receipt photos is recorded", async () => {
    const d = await newAgreedDeal({ minReceipt: 2 });
    await recordEvidence(d, d.supplier, { dispatch: {} }, Buffer.from("dispatch-1"));
    await markInTransit(d);
    await recordEvidence(d, d.buyer, { receipt: {} }, Buffer.from("receipt-1"));
    assert.deepEqual((await fetch(d)).status, { inTransit: {} });
    await recordEvidence(d, d.buyer, { receipt: {} }, Buffer.from("receipt-2"));
    assert.deepEqual((await fetch(d)).status, { inspection: {} });
    // A further receipt photo from the same upload is still accepted in Inspection.
    await recordEvidence(d, d.buyer, { receipt: {} }, Buffer.from("receipt-3"));
    assert.equal((await fetch(d)).receiptEvidenceCount, 3);
  });

  it("only the supplier can mark the shipment in transit", async () => {
    const d = await newAgreedDeal();
    await recordEvidence(d, d.supplier, { dispatch: {} }, Buffer.from("dispatch-1"));
    await expectFail(markInTransit(d, d.buyer), "Unauthorized");
  });

  it("requires four distinct keys", async () => {
    const buyer = Keypair.generate();
    const supplier = Keypair.generate();
    const authority = Keypair.generate();
    await fund(buyer);
    const shipmentId = randomBytes(16);
    await expectFail(
      program.methods
        .createShipment(Array.from(shipmentId), {
          supplier: supplier.publicKey,
          authority: authority.publicKey,
          reviewer: authority.publicKey, // same key as the authority
          termsHash: sha256("terms"),
          invoiceAmountCents: cents(10_000),
          quantity: 100,
          creditPerDefectCents: cents(100),
          maxAdjustmentCents: cents(5_000),
          defectToleranceUnits: 0,
          minDispatchEvidence: 1,
          minReceiptEvidence: 1,
        })
        .accountsPartial({ shipment: shipmentPda(shipmentId), buyer: buyer.publicKey })
        .signers([buyer])
        .rpc(),
      "InvalidParties",
    );
  });

  it("rejects approval of terms that do not match the registered hash", async () => {
    const d = await createDeal();
    await expectFail(approve(d, d.buyer, sha256("different terms")), "TermsHashMismatch");
  });

  it("rejects approval from a stranger", async () => {
    const d = await createDeal();
    const stranger = Keypair.generate();
    await fund(stranger);
    await expectFail(approve(d, stranger), "Unauthorized");
  });

  it("only the supplier can record dispatch evidence", async () => {
    const d = await newAgreedDeal();
    await expectFail(
      recordEvidence(d, d.buyer, { dispatch: {} }, Buffer.from("fake dispatch")),
      "Unauthorized",
    );
  });

  it("a modified evidence file no longer matches its on-chain hash", async () => {
    const d = await newAgreedDeal();
    const original = Buffer.from("dispatch-photo-original");
    const evidence = await recordEvidence(d, d.supplier, { dispatch: {} }, original);

    const stored = await program.account.evidence.fetch(evidence);
    const onChain = Buffer.from(stored.sha256).toString("hex");

    assert.equal(onChain, Buffer.from(sha256(original)).toString("hex"));
    assert.notEqual(onChain, Buffer.from(sha256(Buffer.from("dispatch-photo-edited"))).toString("hex"));
  });

  it("verify_evidence reports whether a file hash matches the record", async () => {
    const d = await newAgreedDeal();
    const original = Buffer.from("dispatch-photo-original");
    const evidence = await recordEvidence(d, d.supplier, { dispatch: {} }, original);

    const check = async (bytes: Buffer) => {
      const { events } = await program.methods
        .verifyEvidence(sha256(bytes))
        .accountsPartial({ shipment: d.shipment, evidence })
        .simulate();
      const ev = events.find((e) => e.name === "evidenceVerified");
      assert.exists(ev, "EvidenceVerified event not emitted");
      return ev!.data.matches as boolean;
    };

    assert.isTrue(await check(original));
    assert.isFalse(await check(Buffer.from("dispatch-photo-edited")));
  });
});
