import { money, type Invoice, type Summary } from "../rest";
import { useApi } from "../useApi";
import { Cell, Page, PageState, Row, StatusPill, Table } from "./ui";

function Card({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-white px-3 py-2">
      <p className="text-[10px] font-medium uppercase tracking-[0.06em] text-neutral-400">{label}</p>
      <p className={`mt-0.5 text-[15px] font-semibold tabular-nums ${tone}`}>{value}</p>
    </div>
  );
}

export function DashboardPage() {
  const summary = useApi<Summary>("/api/summary");
  const invoices = useApi<{ invoices: Invoice[]; count: number }>("/api/invoices");

  return (
    <Page title="Dashboard" meta={summary.data !== null ? `${summary.data.invoiceCount} invoices` : undefined}>
      <PageState loading={summary.loading} error={summary.error}>
        {summary.data !== null ? (
          <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
            <Card label="Revenue" value={money(summary.data.totalRevenue)} />
            <Card label="Expenses" value={money(summary.data.totalExpenses)} />
            <Card
              label="Net income"
              value={money(summary.data.netIncome)}
              tone={Number(summary.data.netIncome) < 0 ? "text-rose-600" : "text-emerald-700"}
            />
            <Card label="Receivables" value={money(summary.data.arOutstanding)} />
            <Card label="Payables" value={money(summary.data.apOutstanding)} />
            <Card label="Cash + bank" value={money(Number(summary.data.cash) + Number(summary.data.bank))} />
          </div>
        ) : null}
      </PageState>

      <h2 className="mt-5 text-[12px] font-semibold text-neutral-700">Recent invoices</h2>
      <div className="mt-2">
        <PageState
          loading={invoices.loading}
          error={invoices.error}
          empty={invoices.data !== null && invoices.data.invoices.length === 0}
        >
          {invoices.data !== null ? (
            <Table
              head={
                <tr>
                  <th className="px-3 py-1.5 text-left font-semibold">Invoice</th>
                  <th className="px-3 py-1.5 text-left font-semibold">Customer</th>
                  <th className="hidden px-3 py-1.5 text-left font-semibold sm:table-cell">Date</th>
                  <th className="px-3 py-1.5 text-right font-semibold">Total</th>
                  <th className="px-3 py-1.5 text-left font-semibold">Status</th>
                </tr>
              }
            >
              {invoices.data.invoices.slice(0, 6).map((invoice) => (
                <Row key={invoice.id}>
                  <Cell className="font-mono text-[11px] text-neutral-500">{invoice.invoiceNumber}</Cell>
                  <Cell>{invoice.customer ?? "—"}</Cell>
                  <Cell className="hidden text-neutral-500 sm:table-cell">{invoice.date}</Cell>
                  <Cell align="right">{money(invoice.total)}</Cell>
                  <Cell>
                    <StatusPill status={invoice.status} />
                  </Cell>
                </Row>
              ))}
            </Table>
          ) : null}
        </PageState>
      </div>
    </Page>
  );
}
