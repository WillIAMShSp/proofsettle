import { useState } from "react";
import { ChevronRight, FileText } from "lucide-react";
import type { Invoice } from "@/lib/api";
import { formatAt, usd } from "@/lib/format";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/** The chat body is the covering note, or "Invoice <number>: <amount> due" without one. */
const hasNote = (invoice: Invoice, body: string) => !body.startsWith(`Invoice ${invoice.number}:`);

function FinalBadge({ invoice }: { invoice: Invoice }) {
  return (
    <span
      className={`inline-block shrink-0 rounded-full border px-2.5 py-0.5 text-[11px] ${
        invoice.final ? "border-success/40 text-success" : "text-muted-foreground"
      }`}
    >
      {invoice.final ? "Final" : "Before defect credit"}
    </span>
  );
}

/**
 * An invoice as sent in the chat: a summary that opens the full invoice in a modal.
 * Invoices are snapshots, so this shows the numbers as issued, never recomputed.
 */
export function InvoiceMessage({
  invoice,
  body,
  mine,
}: {
  invoice: Invoice;
  body: string;
  mine: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      {/* Spans, not divs: a button may only contain phrasing content. */}
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        className={`block w-full rounded-2xl border p-4 text-left text-sm transition hover:border-primary/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 ${
          mine ? "border-primary/40 bg-primary/5" : "bg-muted/20"
        }`}
      >
        <span className="flex items-start justify-between gap-4">
          <span>
            <span className="flex items-center gap-2 font-medium">
              <FileText className="h-4 w-4 text-primary" />
              Invoice {invoice.number}
            </span>
            <span className="mt-1 block text-xs text-muted-foreground">
              {invoice.seller} → {invoice.buyer} · {formatAt(invoice.issuedAt)}
            </span>
          </span>
          <FinalBadge invoice={invoice} />
        </span>
        {hasNote(invoice, body) && (
          <span className="mt-3 block whitespace-pre-wrap break-words">{body}</span>
        )}
        <span className="mt-4 flex items-end justify-between gap-4">
          <span>
            <span className="block text-xs text-muted-foreground">Amount due</span>
            <span className="text-lg font-semibold">{usd(invoice.amountDue)}</span>
          </span>
          <span className="flex items-center gap-1 text-xs text-primary">
            View invoice <ChevronRight className="h-3.5 w-3.5" />
          </span>
        </span>
      </button>
      <InvoiceDialog invoice={invoice} body={body} open={open} onOpenChange={setOpen} />
    </>
  );
}

function InvoiceDialog({
  invoice,
  body,
  open,
  onOpenChange,
}: {
  invoice: Invoice;
  body: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center gap-3 pr-8">
            <DialogTitle className="flex items-center gap-2">
              <FileText className="h-5 w-5 text-primary" />
              Invoice {invoice.number}
            </DialogTitle>
            <FinalBadge invoice={invoice} />
          </div>
          <DialogDescription>
            {invoice.title} · Shipment {invoice.shipmentId}
          </DialogDescription>
        </DialogHeader>

        <dl className="grid grid-cols-2 gap-x-6 gap-y-4 text-sm">
          <div>
            <dt className="text-xs text-muted-foreground">From</dt>
            <dd className="mt-0.5 font-medium">{invoice.seller}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Bill to</dt>
            <dd className="mt-0.5 font-medium">{invoice.buyer}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Issued</dt>
            <dd className="mt-0.5">{formatAt(invoice.issuedAt)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Shipment status when issued</dt>
            <dd className="mt-0.5">{invoice.status}</dd>
          </div>
        </dl>

        {hasNote(invoice, body) && (
          <p className="whitespace-pre-wrap break-words rounded-xl border bg-muted/30 px-4 py-3 text-sm">
            {body}
          </p>
        )}

        <div className="overflow-x-auto rounded-xl border">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-2 text-left font-medium">Description</th>
                <th className="px-4 py-2 text-right font-medium">Qty</th>
                <th className="px-4 py-2 text-right font-medium">Unit price</th>
                <th className="px-4 py-2 text-right font-medium">Amount</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-t">
                <td className="px-4 py-3">{invoice.itemDescription}</td>
                <td className="px-4 py-3 text-right">{invoice.quantity.toLocaleString()}</td>
                <td className="px-4 py-3 text-right">{usd(invoice.unitPrice)}</td>
                <td className="px-4 py-3 text-right">{usd(invoice.subtotal)}</td>
              </tr>
            </tbody>
            <tfoot>
              <tr className="border-t">
                <td colSpan={3} className="px-4 py-2 text-right text-muted-foreground">
                  Subtotal
                </td>
                <td className="px-4 py-2 text-right">{usd(invoice.subtotal)}</td>
              </tr>
              <tr>
                <td colSpan={3} className="px-4 py-2 text-right text-muted-foreground">
                  Defect credit
                </td>
                <td className="px-4 py-2 text-right">
                  {invoice.final && invoice.credit !== null ? (
                    `−${usd(invoice.credit)}`
                  ) : (
                    <span className="text-muted-foreground">Settled later</span>
                  )}
                </td>
              </tr>
              <tr className="border-t text-base font-semibold">
                <td colSpan={3} className="px-4 py-3 text-right">
                  Amount due
                </td>
                <td className="px-4 py-3 text-right">{usd(invoice.amountDue)}</td>
              </tr>
            </tfoot>
          </table>
        </div>

        <p className="text-xs text-muted-foreground">
          {invoice.final
            ? `Settled (${invoice.status}): the agreed amount less the defect credit from the inspection.`
            : `Issued while ${invoice.status}: the agreed amount. Any defect credit is settled after inspection, and a new invoice is sent then.`}{" "}
          The amounts come from the agreed terms and the adjustment; nobody typed them. This invoice
          is a snapshot and doesn't change after it was sent.
        </p>

        <div className="text-xs">
          <p className="text-muted-foreground">Agreed terms hash (what both parties approved)</p>
          <p className="mt-1 break-all font-mono">{invoice.termsHash}</p>
        </div>

        <DialogFooter>
          <DialogClose className="rounded-full border px-6 py-2 text-sm hover:border-primary/60">
            Close
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
