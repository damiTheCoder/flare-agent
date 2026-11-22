/** DSH-style tool-call card: structured arguments while pending, then the
 * parsed ToolResult when the stream reports success or failure. */

import type { ToolCallEvent, ToolResultEvent } from "./api";

type Props = {
  call: ToolCallEvent;
  result?: ToolResultEvent;
  onContextMenu?: (event: React.MouseEvent) => void;
};

type InvoiceLine = { description?: string; quantity?: string; unitPrice?: string; total?: string };
type InvoiceView = {
  invoiceNumber?: string;
  customerName?: string;
  date?: string;
  dueDate?: string;
  subtotal?: string;
  vat?: string;
  total?: string;
  lines?: InvoiceLine[];
};

function parseInvoice(result: ToolResultEvent | undefined, call: ToolCallEvent): InvoiceView | null {
  const args = call.arguments as {
    customerId?: string;
    date?: string;
    items?: Array<{ quantity?: unknown; unitPrice?: unknown }>;
  };
  if (result === undefined) {
    return {
      customerName: args.customerId ?? "—",
      date: args.date,
      lines: (args.items ?? []).map((item) => ({
        description: "catalog item",
        quantity: String(item.quantity ?? ""),
        unitPrice: item.unitPrice === undefined ? "catalog" : String(item.unitPrice),
      })),
    };
  }
  if (!result.ok) return null;
  try {
    const parsed = JSON.parse(result.content) as { invoice?: Record<string, unknown> };
    const invoice = parsed.invoice;
    if (invoice === undefined) return null;
    const lines = (invoice.lines as Array<Record<string, unknown>> | undefined) ?? [];
    return {
      invoiceNumber: String(invoice.invoiceNumber ?? ""),
      customerName: String(invoice.customer ?? args.customerId ?? ""),
      date: String(invoice.date ?? ""),
      dueDate: String(invoice.dueDate ?? ""),
      subtotal: String(invoice.subtotal ?? ""),
      vat: String(invoice.vat ?? ""),
      total: String(invoice.total ?? ""),
      lines: lines.map((line) => ({
        description: String(line.description ?? ""),
        quantity: String(line.quantity ?? ""),
        unitPrice: String(line.unitPrice ?? ""),
        total: String(line.total ?? ""),
      })),
    };
  } catch {
    return null;
  }
}

function statusOf(result: ToolResultEvent | undefined): { key: string; label: string } {
  if (result === undefined) return { key: "pending", label: "Pending" };
  if (result.ok) return { key: "success", label: "Success" };
  return { key: "error", label: "Error" };
}

function money(value: string | undefined): string {
  if (value === undefined || value === "") return "—";
  const amount = Number(value);
  if (Number.isNaN(amount)) return value;
  return `₦${amount.toLocaleString("en-NG", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function ToolCard({ call, result, onContextMenu }: Props) {
  const status = statusOf(result);
  const invoice = call.name === "create_invoice" ? parseInvoice(result, call) : null;

  return (
    <article
      className="tool-card"
      data-testid="tool-card"
      data-tool={call.name}
      data-status={status.key}
      onContextMenu={onContextMenu}
    >
      <header>
        <span className="tool-mark" aria-hidden="true">
          ✦
        </span>
        <span className="tool-name">{call.name}</span>
        <span className={`badge ${status.key}`} data-testid="tool-status">
          {status.label}
        </span>
      </header>

      {invoice !== null ? (
        <div className="tool-body">
          <dl className="kv">
            <dt>Customer</dt>
            <dd>{invoice.customerName || "—"}</dd>
            <dt>Invoice</dt>
            <dd>{invoice.invoiceNumber || "draft (pending)"}</dd>
            <dt>Date</dt>
            <dd>{invoice.date || "—"}</dd>
            <dt>Due</dt>
            <dd>{invoice.dueDate || "—"}</dd>
          </dl>

          <table className="items">
            <thead>
              <tr>
                <th>Item</th>
                <th className="num">Qty</th>
                <th className="num">Unit</th>
                <th className="num">Total</th>
              </tr>
            </thead>
            <tbody>
              {(invoice.lines ?? []).map((line, index) => (
                <tr key={`${line.description}-${index}`}>
                  <td>{line.description}</td>
                  <td className="num">{line.quantity}</td>
                  <td className="num">{line.unitPrice === "catalog" ? "catalog" : money(line.unitPrice)}</td>
                  <td className="num">{line.total === undefined ? "—" : money(line.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <dl className="kv totals">
            <dt>Subtotal</dt>
            <dd>{money(invoice.subtotal)}</dd>
            <dt>VAT 7.5%</dt>
            <dd>{money(invoice.vat)}</dd>
            <dt>Total</dt>
            <dd className="strong">{money(invoice.total)}</dd>
          </dl>

          {result !== undefined && !result.ok ? (
            <p className="tool-error">{result.content}</p>
          ) : null}
        </div>
      ) : (
        <div className="tool-body">
          <dl className="kv">
            <dt>Arguments</dt>
            <dd>
              <code className="args">{JSON.stringify(call.arguments)}</code>
            </dd>
          </dl>
          {result !== undefined ? (
            <pre className={`tool-result ${result.ok ? "" : "error"}`}>{result.content}</pre>
          ) : null}
        </div>
      )}
    </article>
  );
}
