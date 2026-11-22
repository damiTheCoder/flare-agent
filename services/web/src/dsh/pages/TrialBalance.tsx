import { money, type TrialBalance as TrialBalanceData } from "../rest";
import { useApi } from "../useApi";
import { Cell, Page, PageState, Row, Table } from "./ui";

export function TrialBalancePage() {
  const { data, error, loading } = useApi<TrialBalanceData>("/api/trial-balance");

  return (
    <Page title="Trial balance" meta={data !== null ? `${data.accounts.length} accounts` : undefined}>
      <PageState loading={loading} error={error} empty={data !== null && data.accounts.length === 0}>
        {data !== null ? (
          <Table
            head={
              <tr>
                <th className="px-3 py-1.5 text-left font-semibold">Code</th>
                <th className="px-3 py-1.5 text-left font-semibold">Account</th>
                <th className="hidden px-3 py-1.5 text-left font-semibold sm:table-cell">Type</th>
                <th className="px-3 py-1.5 text-right font-semibold">Debit</th>
                <th className="px-3 py-1.5 text-right font-semibold">Credit</th>
                <th className="px-3 py-1.5 text-right font-semibold">Balance</th>
              </tr>
            }
          >
            {data.accounts.map((account) => (
              <Row key={account.id}>
                <Cell className="font-mono text-[11px] text-neutral-500">{account.code}</Cell>
                <Cell>{account.name}</Cell>
                <Cell className="hidden text-neutral-500 sm:table-cell">{account.type}</Cell>
                <Cell align="right">{money(account.debit)}</Cell>
                <Cell align="right">{money(account.credit)}</Cell>
                <Cell align="right" strong>
                  {money(account.balance)}
                </Cell>
              </Row>
            ))}
            <tr className="border-t border-neutral-200 bg-neutral-50 text-[12px] font-semibold">
              <td className="px-3 py-1.5" />
              <td className="px-3 py-1.5" />
              <td className="hidden px-3 py-1.5 sm:table-cell" />
              <Cell align="right" strong>
                {money(data.totalDebit)}
              </Cell>
              <Cell align="right" strong>
                {money(data.totalCredit)}
              </Cell>
              <td className="px-3 py-1.5" />
            </tr>
          </Table>
        ) : null}
      </PageState>
    </Page>
  );
}
