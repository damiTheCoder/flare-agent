import { money, type TrialBalance as TrialBalanceData } from "../rest";
import { useApi } from "../useApi";
import { Cell, Page, PageState, Row, Table } from "./ui";

function titleCase(value: string): string {
  return value.charAt(0) + value.slice(1).toLowerCase();
}

function balanceTone(balance: string): string {
  const amount = Number(balance);
  if (amount < 0) return "text-rose-600";
  if (amount === 0) return "text-neutral-400";
  return "";
}

export function TrialBalancePage() {
  const { data, error, loading } = useApi<TrialBalanceData>("/api/trial-balance");

  return (
    <Page title="Trial balance" meta={data !== null ? `${data.accounts.length} accounts` : undefined}>
      <PageState loading={loading} error={error} empty={data !== null && data.accounts.length === 0}>
        {data !== null ? (
          <Table
            head={
              <tr>
                <th scope="col" className="px-3 py-2 text-left font-semibold">
                  Code
                </th>
                <th scope="col" className="px-3 py-2 text-left font-semibold">
                  Account
                </th>
                <th scope="col" className="hidden px-3 py-2 text-left font-semibold sm:table-cell">
                  Type
                </th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">
                  Debit
                </th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">
                  Credit
                </th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">
                  Balance
                </th>
              </tr>
            }
          >
            {data.accounts.map((account) => (
              <Row key={account.id}>
                <Cell className="font-mono text-[11.5px] text-neutral-500">{account.code}</Cell>
                <Cell>{account.name}</Cell>
                <Cell className="hidden text-neutral-500 sm:table-cell">{titleCase(account.type)}</Cell>
                <Cell align="right" className={Number(account.debit) === 0 ? "text-neutral-400" : ""}>
                  {money(account.debit)}
                </Cell>
                <Cell align="right" className={Number(account.credit) === 0 ? "text-neutral-400" : ""}>
                  {money(account.credit)}
                </Cell>
                <Cell align="right" strong className={balanceTone(account.balance)}>
                  {money(account.balance)}
                </Cell>
              </Row>
            ))}
            <tr className="border-t border-neutral-200 bg-neutral-50 text-[12.5px] font-semibold">
              <td className="px-3 py-[9px]" />
              <td className="px-3 py-[9px]" />
              <td className="hidden px-3 py-[9px] sm:table-cell" />
              <Cell align="right" strong>
                {money(data.totalDebit)}
              </Cell>
              <Cell align="right" strong>
                {money(data.totalCredit)}
              </Cell>
              <td className="px-3 py-[9px]" />
            </tr>
          </Table>
        ) : null}
      </PageState>
    </Page>
  );
}
