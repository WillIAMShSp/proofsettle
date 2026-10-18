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
      program.programId
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
    shipment: PublicKey;
    termsHash: number[];
  }

  /** Creates a shipment in Draft. */
  async function createDeal(): Promise<Deal> {
    const buyer = Keypair.generate();
    const supplier = Keypair.generate();
    const authority = Keypair.generate();
    await fund(buyer, supplier, authority);

    const shipmentId = randomBytes(16);
    const shipment = shipmentPda(shipmentId);
    const termsHash = sha256(`terms-json-v1:${shipmentId.toString("hex")}`);

    await program.methods
      .createShipment(Array.from(shipmentId), {
        supplier: supplier.publicKey,
        authority: authority.publicKey,
        termsHash,
        invoiceAmountCents: cents(10_000),
        quantity: 100,
        creditPerDefectCents: cents(100),
        maxAdjustmentCents: cents(5_000),
      })
      .accountsPartial({ shipment, buyer: buyer.publicKey })
      .signers([buyer])
      .rpc();

    return { buyer, supplier, authority, shipment, termsHash };
  }

  const approve = (d: Deal, who: Keypair, hash: number[] = d.termsHash) =>
    program.methods
      .approveAgreement(hash)
      .accountsPartial({ shipment: d.shipment, approver: who.publicKey })
      .signers([who])
      .rpc();

  async function newAgreedDeal(): Promise<Deal> {
    const d = await createDeal();
    await approve(d, d.buyer);
    await approve(d, d.supplier);
    return d;
  }

  async function recordEvidence(
    d: Deal,
    who: Keypair,
    kind: { dispatch: {} } | { receipt: {} },
    bytes: Buffer
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

  /** Agreed -> dispatch photo -> InTransit -> receipt photo -> Inspection. */
  async function dealInInspection(): Promise<Deal> {
    const d = await newAgreedDeal();
    await recordEvidence(d, d.supplier, { dispatch: {} }, Buffer.from("dispatch-photo-1"));
    await program.methods
      .markInTransit()
      .accountsPartial({ shipment: d.shipment, supplier: d.supplier.publicKey })
      .signers([d.supplier])
      .rpc();
    await recordEvidence(d, d.buyer, { receipt: {} }, Buffer.from("receipt-photo-1"));
    return d;
  }

  const propose = (d: Deal, defects: number, who: Keypair = d.authority) =>
    program.methods
      .proposeAdjustment(defects, sha256("findings-json"), sha256("explanation-text"))
      .accountsPartial({ shipment: d.shipment, authority: who.publicKey })
      .signers([who])
      .rpc();

  // ---- demo cases --------------------------------------------------------

  it("Case A: 3 defects x $100 -> $300 proposal, supplier accepts", async () => {
    const d = await dealInInspection();

    await propose(d, 3);
    let s = await program.account.shipment.fetch(d.shipment);
    assert.deepEqual(s.status, { proposed: {} });
    assert.equal(s.confirmedDefects, 3);
    assert.equal(s.proposedAdjustmentCents.toNumber(), 30_000);

    await program.methods
      .acceptAdjustment()
      .accountsPartial({ shipment: d.shipment, supplier: d.supplier.publicKey })
      .signers([d.supplier])
      .rpc();

    s = await program.account.shipment.fetch(d.shipment);
    assert.deepEqual(s.status, { accepted: {} });
    assert.equal(s.finalAdjustmentCents.toNumber(), 30_000);
    // created, 2 approvals, dispatch evidence, in transit, receipt evidence, proposed, accepted
    assert.equal(s.auditSeq.toNumber(), 8);
  });

  it("Case B: supplier disputes, only the authority can resolve", async () => {
    const d = await dealInInspection();
    await propose(d, 3);

    await program.methods
      .disputeAdjustment(sha256("supplier says damage happened in transit"))
      .accountsPartial({ shipment: d.shipment, supplier: d.supplier.publicKey })
      .signers([d.supplier])
      .rpc();

    let s = await program.account.shipment.fetch(d.shipment);
    assert.deepEqual(s.status, { disputed: {} });

    // The supplier cannot resolve their own dispute.
    await expectFail(
      program.methods
        .resolveDispute(cents(0), sha256("supplier self-resolution"))
        .accountsPartial({ shipment: d.shipment, authority: d.supplier.publicKey })
        .signers([d.supplier])
        .rpc(),
      "Unauthorized"
    );

    await program.methods
      .resolveDispute(cents(200), sha256("reviewer decision"))
      .accountsPartial({ shipment: d.shipment, authority: d.authority.publicKey })
      .signers([d.authority])
      .rpc();

    s = await program.account.shipment.fetch(d.shipment);
    assert.deepEqual(s.status, { resolved: {} });
    assert.equal(s.finalAdjustmentCents.toNumber(), 20_000);
    assert.equal(s.auditSeq.toNumber(), 9);
  });

  // ---- rules and guards --------------------------------------------------

  it("caps the proposal at the agreed maximum", async () => {
    const d = await dealInInspection();
    await propose(d, 60); // 60 x $100 = $6,000 > $5,000 cap
    const s = await program.account.shipment.fetch(d.shipment);
    assert.equal(s.proposedAdjustmentCents.toNumber(), 500_000);
  });

  it("rejects more defects than the shipment quantity", async () => {
    const d = await dealInInspection();
    await expectFail(propose(d, 101), "DefectsExceedQuantity");
  });

  it("only the authority can propose an adjustment", async () => {
    const d = await dealInInspection();
    await expectFail(propose(d, 3, d.supplier), "Unauthorized");
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
      "Unauthorized"
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
