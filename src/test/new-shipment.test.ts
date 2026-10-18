import { describe, expect, it } from "vitest";
import { INITIAL_FORM, buildNewShipment, toCents, type NewShipmentForm } from "@/lib/new-shipment";

const filled: NewShipmentForm = {
  ...INITIAL_FORM,
  title: " Steel brackets ",
  supplier: "Ferro Precision Works",
  recipientEmail: " Ops@Ferro.example ",
  itemDescription: "Machined steel bracket",
};

const errorFor = (patch: Partial<NewShipmentForm>) => {
  const built = buildNewShipment({ ...filled, ...patch });
  return built.ok ? null : built.error;
};

describe("toCents", () => {
  it("reads dollars with up to 2 decimals exactly", () => {
    expect(toCents("12.07")).toBe(1207);
    expect(toCents("0.1")).toBe(10);
    expect(toCents("100")).toBe(10000);
  });
  it("rejects anything else", () => {
    for (const bad of ["", "1.234", "-5", "1e3", "abc", "1."]) expect(toCents(bad)).toBeNull();
  });
});

describe("buildNewShipment", () => {
  it("builds the API body from the defaults", () => {
    const built = buildNewShipment(filled);
    expect(built).toEqual({
      ok: true,
      body: {
        title: "Steel brackets",
        supplier: "Ferro Precision Works",
        recipientEmail: "ops@ferro.example",
        terms: {
          itemDescription: "Machined steel bracket",
          quantity: 100,
          unitPrice: 100,
          invoiceAmount: 10000,
          evidenceRequirements: {
            minDispatchPhotos: 4,
            minReceiptPhotos: 4,
            inspectionWindowHours: 48,
          },
          acceptance: {
            defectTypes: ["bend", "crack", "deep_scratch", "discoloration"],
            minConfidence: 0.85,
            defectToleranceUnits: 0,
          },
          compensation: { type: "per_defective_unit", amountPerUnit: 100, maxCredit: 10000 },
        },
      },
    });
  });

  it("computes the invoice in cents, so it equals quantity × unit price exactly", () => {
    const built = buildNewShipment({
      ...filled,
      quantity: "3",
      unitPrice: "0.10",
      amountPerUnit: "0.05",
    });
    if (!built.ok) throw new Error(built.error);
    expect(built.body.terms.invoiceAmount).toBe(0.3); // not 0.30000000000000004
    expect(built.body.terms.compensation.maxCredit).toBe(0.3);
  });

  it("refuses terms the backend or the on-chain program would reject", () => {
    expect(errorFor({ supplier: " " })).toMatch(/manufacturer/);
    expect(errorFor({ recipientEmail: "" })).toMatch(/email/);
    expect(errorFor({ recipientEmail: "ops@ferro" })).toMatch(/email/);
    expect(errorFor({ recipientEmail: "a b@ferro.example" })).toMatch(/email/);
    expect(errorFor({ quantity: "0" })).toMatch(/Quantity/);
    expect(errorFor({ unitPrice: "1.999" })).toMatch(/Unit price/);
    expect(errorFor({ maxCredit: "10000.01" })).toMatch(/exceed/);
    expect(errorFor({ defectTypes: "Deep Scratch" })).toMatch(/lowercase/);
    expect(errorFor({ defectTypes: "bend, bend" })).toMatch(/once/);
    expect(errorFor({ minConfidencePct: "101" })).toMatch(/confidence/);
    expect(errorFor({ defectToleranceUnits: "101" })).toMatch(/Tolerated/);
    expect(errorFor({ minReceiptPhotos: "21" })).toMatch(/Photo/);
  });
});
