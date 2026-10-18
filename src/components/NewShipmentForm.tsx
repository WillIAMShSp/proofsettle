import { useNavigate } from "@tanstack/react-router";
import { useState, type ReactNode } from "react";
import { usd } from "@/lib/format";
import {
  INITIAL_FORM,
  buildNewShipment,
  toCents,
  toInt,
  type NewShipmentForm as Form,
} from "@/lib/new-shipment";
import { useCreateShipment } from "@/lib/queries";
import { ErrorNote } from "@/lib/store";

const input =
  "mt-1 w-full rounded-lg border bg-background/50 px-3 py-2 text-sm outline-none focus:border-primary/60";

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-[11px] font-medium text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-muted-foreground">{hint}</span>}
    </label>
  );
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="space-y-3">
      <legend className="mb-3 text-sm font-medium">{title}</legend>
      <div className="grid gap-3 sm:grid-cols-2">{children}</div>
    </fieldset>
  );
}

/** The Buyer drafts a shipment and its agreement terms; the manufacturer approves them next. */
export function NewShipmentForm({ onCancel }: { onCancel: () => void }) {
  const [f, setF] = useState<Form>(INITIAL_FORM);
  const [error, setError] = useState<string | null>(null);
  const create = useCreateShipment();
  const nav = useNavigate();

  const set = (key: keyof Form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setF((prev) => ({ ...prev, [key]: e.target.value }));
  const text = (key: keyof Form, placeholder?: string) => (
    <input value={f[key]} onChange={set(key)} placeholder={placeholder} className={input} />
  );
  const num = (key: keyof Form, step = "1") => (
    <input
      value={f[key]}
      onChange={set(key)}
      type="number"
      min="0"
      step={step}
      inputMode="decimal"
      className={input}
    />
  );

  const unitCents = toCents(f.unitPrice);
  const quantity = toInt(f.quantity);
  const invoice = unitCents && quantity ? usd((unitCents * quantity) / 100) : "—";

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const built = buildNewShipment(f);
    if (!built.ok) {
      setError(built.error);
      return;
    }
    create.mutate(built.body, {
      onSuccess: (detail) => nav({ to: "/shipments/$id", params: { id: detail.id } }),
    });
  }

  return (
    <form onSubmit={submit} className="card-surface space-y-8 p-6 fade-up">
      <div>
        <h2 className="text-lg font-medium">New shipment</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          These terms are what both parties approve. Once approved they can't change, and every
          adjustment is computed from them.
        </p>
      </div>

      <Group title="Shipment">
        <Field label="Title">{text("title", "Steel brackets, Q4 order")}</Field>
        <Field label="Manufacturer">{text("supplier", "Ferro Precision Works")}</Field>
        <Field
          label="Manufacturer's email"
          hint="Their ProofSettle sign-in. The shipment shows on their dashboard, and only to them, you and Reviewers."
        >
          <input
            value={f.recipientEmail}
            onChange={set("recipientEmail")}
            type="email"
            autoComplete="off"
            placeholder="ops@ferro.com"
            className={input}
          />
        </Field>
        <Field label="Item description">{text("itemDescription", "Machined steel bracket")}</Field>
        <Field label="Quantity (units)">{num("quantity")}</Field>
        <Field label="Unit price ($)" hint={`Invoice: ${invoice}`}>
          {num("unitPrice", "0.01")}
        </Field>
      </Group>

      <Group title="Defects and credit">
        <Field label="Defect types" hint="Comma-separated, e.g. bend, crack, deep_scratch">
          {text("defectTypes")}
        </Field>
        <Field label="Min AI confidence (%)" hint="Findings below this need a human review">
          {num("minConfidencePct")}
        </Field>
        <Field label="Tolerated defective units" hint="Defects accepted without credit">
          {num("defectToleranceUnits")}
        </Field>
        <Field label="Credit per defective unit ($)">{num("amountPerUnit", "0.01")}</Field>
        <Field label="Max credit ($)" hint="Leave empty to cap at the invoice amount">
          {num("maxCredit", "0.01")}
        </Field>
      </Group>

      <Group title="Evidence">
        <Field label="Min dispatch photos (manufacturer)">{num("minDispatchPhotos")}</Field>
        <Field label="Min receipt photos (buyer)">{num("minReceiptPhotos")}</Field>
        <Field label="Inspection window (hours)" hint="After receipt, for the buyer to inspect">
          {num("inspectionWindowHours")}
        </Field>
      </Group>

      {error && <p className="text-sm text-destructive">{error}</p>}
      <ErrorNote error={create.error} />

      <div className="flex flex-wrap gap-3">
        <button
          type="submit"
          disabled={create.isPending}
          className="rounded-full bg-sol px-8 py-2.5 font-medium text-background hover:opacity-90 disabled:opacity-40"
        >
          {create.isPending ? "Creating…" : "Create shipment"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={create.isPending}
          className="rounded-full border px-6 py-2.5 text-sm hover:border-primary/60 disabled:opacity-40"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
