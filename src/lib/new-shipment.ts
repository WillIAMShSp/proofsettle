// The new-shipment form's fields and the request body built from them.

import type { NewShipment } from "./api";

// The backend validates every field again (app/terms.py); these checks only give earlier,
// friendlier messages. Photo minimums stay at or under 20 each: one upload takes at most 20
// files, and the on-chain program allows 64 evidence records per shipment in total.
export const MAX_PHOTOS = 20;
const DEFECT_TYPE = /^[a-z][a-z0-9_]*$/;
// The backend's check (app/routes.py Email).
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
// The mock inspection reports these types (backend/app/fixtures/mock_inspection.json).
export const DEFAULT_DEFECTS = "bend, crack, deep_scratch, discoloration";

export type NewShipmentForm = {
  title: string;
  supplier: string;
  recipientEmail: string;
  itemDescription: string;
  quantity: string;
  unitPrice: string;
  amountPerUnit: string;
  maxCredit: string;
  defectTypes: string;
  minConfidencePct: string;
  defectToleranceUnits: string;
  minDispatchPhotos: string;
  minReceiptPhotos: string;
  inspectionWindowHours: string;
};

export const INITIAL_FORM: NewShipmentForm = {
  title: "",
  supplier: "",
  recipientEmail: "",
  itemDescription: "",
  quantity: "100",
  unitPrice: "100",
  amountPerUnit: "100",
  maxCredit: "",
  defectTypes: DEFAULT_DEFECTS,
  minConfidencePct: "85",
  defectToleranceUnits: "0",
  minDispatchPhotos: "4",
  minReceiptPhotos: "4",
  inspectionWindowHours: "48",
};

/** Whole cents for a dollar string with at most 2 decimals, else null. */
export function toCents(value: string): number | null {
  const v = value.trim();
  if (!/^\d+(\.\d{1,2})?$/.test(v)) return null;
  const [whole, frac = ""] = v.split(".");
  return Number(whole) * 100 + Number(frac.padEnd(2, "0"));
}

export function toInt(value: string): number | null {
  const v = value.trim();
  return /^\d+$/.test(v) ? Number(v) : null;
}

type Built = { ok: true; body: NewShipment };
type Failed = { ok: false; error: string };

export function buildNewShipment(f: NewShipmentForm): Built | Failed {
  const fail = (error: string): Failed => ({ ok: false, error });
  const title = f.title.trim();
  const supplier = f.supplier.trim();
  const itemDescription = f.itemDescription.trim();
  if (!title) return fail("Give the shipment a title.");
  if (title.length > 200) return fail("Keep the title under 200 characters.");
  if (!supplier) return fail("Name the manufacturer.");
  if (supplier.length > 200) return fail("Keep the manufacturer name under 200 characters.");
  const recipientEmail = f.recipientEmail.trim().toLowerCase();
  if (!recipientEmail) return fail("Enter the manufacturer's account email.");
  if (!EMAIL.test(recipientEmail) || recipientEmail.length > 320)
    return fail("The manufacturer's email doesn't look right, e.g. ops@ferro.com.");
  if (!itemDescription) return fail("Describe the item being shipped.");
  if (itemDescription.length > 500) return fail("Keep the item description under 500 characters.");

  const quantity = toInt(f.quantity);
  if (!quantity || quantity > 1_000_000)
    return fail("Quantity must be a whole number from 1 to 1,000,000.");
  const unitCents = toCents(f.unitPrice);
  if (!unitCents) return fail("Unit price must be a positive dollar amount, e.g. 12.50.");
  const invoiceCents = unitCents * quantity;
  if (invoiceCents > 999_999_999_999) return fail("The invoice is too large.");

  const perUnitCents = toCents(f.amountPerUnit);
  if (!perUnitCents) return fail("Credit per defective unit must be a positive dollar amount.");
  const maxCreditCents = f.maxCredit.trim() ? toCents(f.maxCredit) : invoiceCents;
  if (!maxCreditCents) return fail("Max credit must be a positive dollar amount.");
  if (maxCreditCents > invoiceCents) return fail("Max credit can't exceed the invoice amount.");

  const defectTypes = f.defectTypes
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
  if (!defectTypes.length) return fail("List at least one defect type.");
  const badType = defectTypes.find((t) => !DEFECT_TYPE.test(t) || t.length > 64);
  if (badType)
    return fail(`"${badType}": defect types are lowercase words joined by _, e.g. deep_scratch.`);
  if (new Set(defectTypes).size !== defectTypes.length)
    return fail("Each defect type can be listed once.");

  const confidencePct = toInt(f.minConfidencePct);
  if (!confidencePct || confidencePct > 100)
    return fail("Min AI confidence must be from 1 to 100%.");
  const tolerance = toInt(f.defectToleranceUnits);
  if (tolerance === null || tolerance > quantity)
    return fail("Tolerated defects must be from 0 to the quantity.");

  const minDispatchPhotos = toInt(f.minDispatchPhotos);
  const minReceiptPhotos = toInt(f.minReceiptPhotos);
  if (
    !minDispatchPhotos ||
    minDispatchPhotos > MAX_PHOTOS ||
    !minReceiptPhotos ||
    minReceiptPhotos > MAX_PHOTOS
  )
    return fail(`Photo minimums must be from 1 to ${MAX_PHOTOS}.`);
  const windowHours = toInt(f.inspectionWindowHours);
  if (!windowHours || windowHours > 24 * 90)
    return fail("The inspection window must be from 1 to 2160 hours.");

  return {
    ok: true,
    body: {
      title,
      supplier,
      recipientEmail,
      terms: {
        itemDescription,
        quantity,
        unitPrice: unitCents / 100,
        invoiceAmount: invoiceCents / 100,
        evidenceRequirements: {
          minDispatchPhotos,
          minReceiptPhotos,
          inspectionWindowHours: windowHours,
        },
        acceptance: {
          defectTypes,
          minConfidence: confidencePct / 100,
          defectToleranceUnits: tolerance,
        },
        compensation: {
          type: "per_defective_unit",
          amountPerUnit: perUnitCents / 100,
          maxCredit: maxCreditCents / 100,
        },
      },
    },
  };
}
