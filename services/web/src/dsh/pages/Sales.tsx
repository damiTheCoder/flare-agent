import { money, type Bill, type Invoice } from "../rest";
import { useApi } from "../useApi";
import { Cell, Page, PageState, Row, StatusPill, Table } from "./ui";

/** Zero money is de-emphasised so real amounts carry the eye. */
function zeroTone(value: string | number | undefined): string {
  return Number(value ?? 0) === 0 ? "text-neutral-400" : "";
}

export function SalesPage() {
  const { data, error, loading } = useApi<{ invoices: Invoice[]; count: number }>("/api/invoices");

  return (
    <Page title="Invoices" meta={data !== null ? `${data.count} invoices` : undefined}>
      <PageState loading={loading} error={error} empty={data !== null && data.count === 0}>
        {data !== null ? (
          <Table
            head={
              <tr>
                <th scope="col" className="px-3 py-2 text-left font-semibold">Invoice</th>
                <th scope="col" className="px-3 py-2 text-left font-semibold">Customer</th>
                <th scope="col" className="hidden px-3 py-2 text-left font-semibold sm:table-cell">Date</th>
                <th scope="col" className="hidden px-3 py-2 text-left font-semibold md:table-cell">Due</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Total</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Paid</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Outstanding</th>
                <th scope="col" className="px-3 py-2 text-left font-semibold">Status</th>
              </tr>
            }
          >
            {data.invoices.map((invoice) => (
              <Row key={invoice.id}>
                <Cell className="font-mono text-[11.5px] text-neutral-500">{invoice.invoiceNumber}</Cell>
                <Cell>{invoice.customer ?? "—"}</Cell>
                <Cell className="hidden text-neutral-500 sm:table-cell">{invoice.date}</Cell>
                <Cell className="hidden text-neutral-500 md:table-cell">{invoice.dueDate}</Cell>
                <Cell align="right">{money(invoice.total)}</Cell>
                <Cell align="right" className={zeroTone(invoice.amountPaid)}>
                  {money(invoice.amountPaid)}
                </Cell>
                <Cell align="right" strong className={zeroTone(invoice.outstanding)}>
                  {money(invoice.outstanding)}
                </Cell>
                <Cell>
                  <StatusPill status={invoice.status} />
                </Cell>
              </Row>
            ))}
          </Table>
        ) : null}
      </PageState>
    </Page>
  );
}

export function PurchasesPage() {
  const { data, error, loading } = useApi<{ bills: Bill[]; count: number }>("/api/bills");

  return (
    <Page title="Bills" meta={data !== null ? `${data.count} bills` : undefined}>
      <PageState loading={loading} error={error} empty={data !== null && data.count === 0}>
        {data !== null ? (
          <Table
            head={
              <tr>
                <th scope="col" className="px-3 py-2 text-left font-semibold">Bill</th>
                <th scope="col" className="px-3 py-2 text-left font-semibold">Vendor</th>
                <th scope="col" className="hidden px-3 py-2 text-left font-semibold sm:table-cell">Date</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Total</th>
                <th scope="col" className="hidden px-3 py-2 text-right font-semibold md:table-cell">WHT</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Net payable</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Paid</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Outstanding</th>
                <th scope="col" className="px-3 py-2 text-left font-semibold">Status</th>
              </tr>
            }
          >
            {data.bills.map((bill) => (
              <Row key={bill.id}>
                <Cell className="font-mono text-[11.5px] text-neutral-500">{bill.billNumber}</Cell>
                <Cell>{bill.vendor ?? "—"}</Cell>
                <Cell className="hidden text-neutral-500 sm:table-cell">{bill.date}</Cell>
                <Cell align="right">{money(bill.total)}</Cell>
                <Cell align="right" className="hidden md:table-cell">
                  {money(Number(bill.total) - Number(bill.netPayable))}
                </Cell>
                <Cell align="right">{money(bill.netPayable)}</Cell>
                <Cell align="right" className={zeroTone(bill.amountPaid)}>
                  {money(bill.amountPaid)}
                </Cell>
                <Cell align="right" strong className={zeroTone(bill.outstanding)}>
                  {money(bill.outstanding)}
                </Cell>
                <Cell>
                  <StatusPill status={bill.status} />
                </Cell>
              </Row>
            ))}
          </Table>
        ) : null}
      </PageState>
    </Page>
  );
}
