import { money, type Aging, type AgingRow } from "../rest";
import { useApi } from "../useApi";
import { Cell, Page, PageState, Row, Table } from "./ui";

function BucketCard({ label, count, total }: { label: string; count: number; total: string }) {
  return (
    <div
      className={`rounded-lg border bg-white px-3.5 py-2.5 ${
        count === 0 ? "border-neutral-200" : "border-neutral-300"
      }`}
    >
      <p className="text-[10.5px] font-medium uppercase tracking-[0.06em] text-neutral-400">{label}</p>
      <p className="mt-1 text-[16px] font-semibold leading-none tabular-nums text-neutral-900">
        {money(total)}
      </p>
      <p className="mt-1 text-[11px] text-neutral-400">
        {count} {count === 1 ? "item" : "items"}
      </p>
    </div>
  );
}

function AgingPage({ kind }: { kind: "ar" | "ap" }) {
  const path = kind === "ar" ? "/api/aging/ar" : "/api/aging/ap";
  const { data, error, loading } = useApi<Aging>(path);
  const rows: AgingRow[] = data !== null ? (kind === "ar" ? (data.invoices ?? []) : (data.bills ?? [])) : [];

  const title = kind === "ar" ? "AR aging" : "AP aging";
  const document = kind === "ar" ? "Invoice" : "Bill";
  const party = kind === "ar" ? "Customer" : "Vendor";

  return (
    <Page
      title={title}
      meta={
        data !== null
          ? `As of ${data.asOf} · ${money(data.totalOutstanding)} outstanding`
          : undefined
      }
    >
      <PageState loading={loading} error={error}>
        {data !== null ? (
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-5">
            {data.buckets.map((bucket) => (
              <BucketCard key={bucket.key} label={bucket.label} count={bucket.count} total={bucket.total} />
            ))}
          </div>
        ) : null}
      </PageState>

      <div className="mt-4">
        <PageState loading={loading} error={error} empty={data !== null && rows.length === 0}>
          {data !== null ? (
            <Table
              head={
                <tr>
                  <th scope="col" className="px-3 py-2 text-left font-semibold">{document}</th>
                  <th scope="col" className="px-3 py-2 text-left font-semibold">{party}</th>
                  <th scope="col" className="hidden px-3 py-2 text-left font-semibold sm:table-cell">Due</th>
                  <th scope="col" className="hidden px-3 py-2 text-right font-semibold md:table-cell">Days</th>
                  <th scope="col" className="px-3 py-2 text-left font-semibold">Bucket</th>
                  <th scope="col" className="px-3 py-2 text-right font-semibold">Outstanding</th>
                </tr>
              }
            >
              {rows.map((row, index) => (
                <Row key={row.invoiceId ?? row.billId ?? index}>
                  <Cell className="font-mono text-[11px] text-neutral-500">
                    {row.invoiceNumber ?? row.billNumber ?? "—"}
                  </Cell>
                  <Cell>{(kind === "ar" ? row.customer : row.vendor) ?? "—"}</Cell>
                  <Cell className="hidden text-neutral-500 sm:table-cell">{row.dueDate ?? "—"}</Cell>
                  <Cell align="right" className="hidden md:table-cell">
                    {row.daysPastDue}
                  </Cell>
                  <Cell className="capitalize text-neutral-500">{row.bucket}</Cell>
                  <Cell align="right" strong>
                    {money(row.outstanding)}
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

export function ArAgingPage() {
  return <AgingPage kind="ar" />;
}

export function ApAgingPage() {
  return <AgingPage kind="ap" />;
}
