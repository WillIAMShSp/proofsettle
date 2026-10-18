import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { InvoiceMessage } from "@/components/InvoiceView";
import type { Invoice } from "@/lib/api";

const settled: Invoice = {
  number: "INV-PS-1031-01",
  issuedAt: "2026-10-18T09:30:00Z",
  shipmentId: "PS-1031",
  title: "250 steel brackets",
  seller: "Ferro Precision Works",
  buyer: "Northgate Assembly Ltd",
  itemDescription: "Steel mounting bracket",
  quantity: 250,
  unitPrice: 15,
  subtotal: 3750,
  final: true,
  credit: 15,
  amountDue: 3735,
  status: "Resolved",
  termsHash: "a".repeat(64),
};

describe("InvoiceMessage", () => {
  it("opens the full invoice in a modal when clicked, and closes it", () => {
    render(
      <InvoiceMessage invoice={settled} body="Invoice INV-PS-1031-01: $3,735 due" mine={false} />,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Invoice INV-PS-1031-01/ }));
    const dialog = screen.getByRole("dialog");
    const d = within(dialog);
    expect(d.getByRole("heading", { name: /Invoice INV-PS-1031-01/ })).toBeInTheDocument();
    expect(d.getByText("Steel mounting bracket")).toBeInTheDocument();
    expect(d.getAllByText("$3,750")).toHaveLength(2); // line amount and subtotal
    expect(d.getByText("−$15")).toBeInTheDocument();
    expect(d.getByText("$3,735")).toBeInTheDocument();
    expect(d.getByText("Final")).toBeInTheDocument();
    expect(d.getByText("a".repeat(64))).toBeInTheDocument();

    // Two "Close" buttons: the corner X (screen-reader label) and the footer one.
    const close = d.getAllByRole("button", { name: "Close" }).at(-1);
    if (!close) throw new Error("no Close button");
    fireEvent.click(close);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows a covering note, and no credit before settlement", () => {
    const early = {
      ...settled,
      final: false,
      credit: null,
      amountDue: 3750,
      status: "Agreed",
    } as const;
    render(<InvoiceMessage invoice={early} body="Payment terms: net 30" mine />);
    expect(screen.getByText("Payment terms: net 30")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Invoice INV-PS-1031-01/ }));
    const d = within(screen.getByRole("dialog"));
    expect(d.getByText("Before defect credit")).toBeInTheDocument();
    expect(d.getByText("Settled later")).toBeInTheDocument();
    expect(d.getByText("Payment terms: net 30")).toBeInTheDocument();
    expect(d.getAllByText("$3,750")).toHaveLength(3); // line, subtotal, amount due
  });
});
