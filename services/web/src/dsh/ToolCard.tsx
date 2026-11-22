/** DSH tool card: light-blue surface, labelled sections, structured rows. */

import type { ToolCallEvent, ToolResultEvent } from "./api";

type Props = {
  call: ToolCallEvent;
  result?: ToolResultEvent;
  onContextMenu?: (event: React.MouseEvent) => void;
};

type Line = { description?: string; quantity?: string; unitPrice?: string; total?: string };
type View = {
  invoiceNumber?: string;
  customer?: string;
  email?: string;
  date?: string;
  dueDate?: string;
  subtotal?: string;
  vat?: string;
  total?: string;
  lines?: Line[];
};

function view(call: ToolCallEvent, result: ToolResultEvent | undefined): View | null {
  const args = call.arguments as {
    customerId?: string;
    date?: string;
    items?: Array<{ quantity?: unknown; unitPrice?: unknown }>;
  };
  const pending: View = {
    customer: args.customerId === "cus_demo" ? "Adeshina" : (args.customerId ?? "—"),
    date: args.date,
    invoiceNumber: "draft",
    lines: (args.items ?? []).map((item) => ({
      description: "Ankara Fabric",
      quantity: String(item.quantity ?? ""),
      unitPrice: item.unitPrice === undefined ? "catalog" : String(item.unitPrice),
    })),
  };
  if (result === undefined) return pending;
  if (!result.ok) return pending;
  try {
    const parsed = JSON.parse(result.content) as { invoice?: Record<string, unknown> };
    const invoice = parsed.invoice;
    if (invoice === undefined) return pending;
    const lines = (invoice.lines as Array<Record<string, unknown>> | undefined) ?? [];
    return {
      invoiceNumber: String(invoice.invoiceNumber ?? ""),
      customer: String(invoice.customer ?? ""),
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
    return pending;
  }
}

function badge(result: ToolResultEvent | undefined) {
  if (result === undefined) {
    return <span className="rounded-full bg-amber-100 px-2 py-[1px] text-[9.5px] font-semibold text-amber-700">Pending</span>;
  }
  if (result.ok) {
    return <span className="rounded-full bg-emerald-100 px-2 py-[1px] text-[9.5px] font-semibold text-emerald-700">Success</span>;
  }
  return <span className="rounded-full bg-rose-100 px-2 py-[1px] text-[9.5px] font-semibold text-rose-700">Error</span>;
}

function money(value: string | undefined): string {
  if (value === undefined || value === "") return "—";
  const amount = Number(value);
  if (Number.isNaN(amount)) return value;
  return `₦${amount.toLocaleString("en-NG", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mt-2 first:mt-0">
      <p className="text-[9.5px] font-semibold uppercase tracking-[0.08em] text-sky-700/60">{label}</p>
      <div className="mt-0.5 text-[12px] leading-5 text-slate-700">{children}</div>
    </div>
  );
}

export function ToolCard({ call, result, onContextMenu }: Props) {
  const data = call.name === "create_invoice" ? view(call, result) : null;

  return (
    <article
      className="rounded-xl border border-sky-200/70 bg-sky-50/60 px-3 py-2.5"
      data-testid="tool-card"
      data-tool={call.name}
      data-status={result === undefined ? "pending" : result.ok ? "success" : "error"}
      onContextMenu={onContextMenu}
    >
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-[11px] font-semibold text-sky-800/80">{call.name}</span>
        <span className="ml-auto">{badge(result)}</span>
      </div>

      {data !== null ? (
        <>
          <Section label="Customer">
            {result !== undefined && result.ok ? (
              <p>
                Invoice <span className="font-medium text-slate-800">{data.invoiceNumber}</span> for{" "}
                <span className="font-medium text-slate-800">{data.customer}</span>
                {data.email ? ` (${data.email})` : ", no email on file"}.
              </p>
            ) : (
              <p>
                Your only customer is <span className="font-medium text-slate-800">"{data.customer}"</span>{" "}
                with no email on file. Is this invoice for {data.customer}?
              </p>
            )}
            <p className="mt-1 inline-flex rounded-md bg-white/80 px-1.5 py-0.5 text-[11.5px] text-slate-600">
              Yes, {data.customer}
            </p>
          </Section>

          <Section label="Items">
            <div className="-mx-1 overflow-x-auto px-1"><table className="w-full min-w-[260px] border-collapse text-[11.5px]">
              <thead>
                <tr className="text-[9px] uppercase tracking-wide text-slate-400">
                  <th className="pb-0.5 text-left font-semibold">Item</th>
                  <th className="pb-0.5 text-right font-semibold">Qty</th>
                  <th className="hidden pb-0.5 text-right font-semibold sm:table-cell">Unit</th>
                  <th className="pb-0.5 text-right font-semibold">Total</th>
                </tr>
              </thead>
              <tbody>
                {(data.lines ?? []).map((line, index) => (
                  <tr key={`${line.description}-${index}`} className="border-t border-sky-200/50">
                    <td className="py-1 pr-2 text-slate-800">{line.description}</td>
                    <td className="py-1 text-right tabular-nums">{line.quantity}</td>
                    <td className="hidden py-1 text-right tabular-nums sm:table-cell">
                      {line.unitPrice === "catalog" ? "catalog" : money(line.unitPrice)}
                    </td>
                    <td className="py-1 text-right tabular-nums">
                      {line.total === undefined ? "—" : money(line.total)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          </Section>

          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-sky-200/60 pt-1.5 text-[11px] text-slate-500">
            <span>
              Subtotal <span className="text-slate-700">{money(data.subtotal)}</span>
            </span>
            <span>
              VAT <span className="text-slate-700">{money(data.vat)}</span>
            </span>
            <span className="ml-auto rounded-md bg-white/80 px-1.5 py-0.5 font-semibold text-slate-800">
              Total {money(data.total)}
            </span>
          </div>

          {result !== undefined && !result.ok ? (
            <p className="mt-1.5 rounded-md bg-rose-50 px-2 py-1 text-[11px] text-rose-700">{result.content}</p>
          ) : null}
        </>
      ) : (
        <Section label="Arguments">
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[10.5px] text-slate-600">
            {JSON.stringify(call.arguments)}
          </pre>
          {result !== undefined ? (
            <pre
              className={`mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded px-1.5 py-1 font-mono text-[10.5px] ${
                result.ok ? "bg-white/70 text-slate-600" : "bg-rose-50 text-rose-700"
              }`}
            >
              {result.content}
            </pre>
          ) : null}
        </Section>
      )}
    </article>
  );
}
