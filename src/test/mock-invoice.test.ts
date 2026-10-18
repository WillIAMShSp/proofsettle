import { beforeEach, describe, expect, it } from "vitest";
import { ROLE_KEY } from "@/lib/api";
import { mockApi } from "@/lib/mock-api";

const as = (role: "Buyer" | "Supplier" | "Reviewer") => localStorage.setItem(ROLE_KEY, role);

describe("mock invoices (same rules as the backend)", () => {
  beforeEach(async () => {
    localStorage.clear();
    as("Buyer");
    await mockApi.devReset();
  });

  it("lets the manufacturer invoice the agreed amount before settlement", async () => {
    as("Supplier");
    const m = await mockApi.sendInvoice("PS-1038");
    expect(m.invoice).toMatchObject({
      number: "INV-PS-1038-01",
      quantity: 40,
      subtotal: 6400,
      final: false,
      credit: null,
      amountDue: 6400,
      status: "In Transit",
    });
    expect(m.body).toBe("Invoice INV-PS-1038-01: $6,400 due");

    as("Buyer");
    const thread = await mockApi.listMessages("PS-1038");
    expect(thread.map((x) => [x.invoice?.number, x.mine])).toEqual([["INV-PS-1038-01", false]]);
    as("Supplier");
    expect((await mockApi.sendInvoice("PS-1038")).invoice?.number).toBe("INV-PS-1038-02");
  });

  it("charges the settlement amount once settled", async () => {
    as("Supplier");
    const adj = (await mockApi.getShipment("PS-1031")).adjustment!;
    const inv = (await mockApi.sendInvoice("PS-1031")).invoice!;
    expect(inv.final).toBe(true);
    expect(inv.credit).toBe(adj.credit);
    expect(inv.amountDue).toBe(adj.settlementAmount);
  });

  it("refuses anyone but the manufacturer", async () => {
    for (const role of ["Buyer", "Reviewer"] as const) {
      as(role);
      await expect(mockApi.sendInvoice("PS-1038")).rejects.toMatchObject({ status: 403 });
    }
  });

  it("keeps plain messages free of invoices", async () => {
    const m = await mockApi.sendMessage("PS-1042", " hello ");
    expect(m).toMatchObject({ body: "hello", invoice: null, mine: true });
  });
});
