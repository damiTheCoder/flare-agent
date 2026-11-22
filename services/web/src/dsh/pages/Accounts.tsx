import { money, type Account } from "../rest";
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

export function ChartOfAccountsPage() {
  const { data, error, loading } = useApi<{ accounts: Account[]; count: number }>("/api/accounts");

  return (
    <Page title="Chart of accounts" meta={data !== null ? `${data.count} accounts` : undefined}>
      <PageState loading={loading} error={error} empty={data !== null && data.count === 0}>
        {data !== null ? (
          <Table
            head={
              <tr>
                <th scope="col" className="px-3 py-2 text-left font-semibold">
                  Code
                </th>
                <th scope="col" className="px-3 py-2 text-left font-semibold">
                  Name
                </th>
                <th scope="col" className="px-3 py-2 text-left font-semibold">
                  Type
                </th>
                <th scope="col" className="hidden px-3 py-2 text-left font-semibold sm:table-cell">
                  Category
                </th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">
                  Balance
                </th>
              </tr>
            }
          >
            {data.accounts.map((account) => (
              <Row key={account.id}>
                <Cell className="w-16 font-mono text-[11.5px] text-neutral-500">{account.code}</Cell>
                <Cell>{account.name}</Cell>
                <Cell className="text-neutral-500">{titleCase(account.type)}</Cell>
                <Cell className="hidden text-neutral-500 sm:table-cell">{account.category}</Cell>
                <Cell align="right" strong className={balanceTone(account.balance)}>
                  {money(account.balance)}
                </Cell>
              </Row>
            ))}
          </Table>
        ) : null}
      </PageState>
    </Page>
  );
}
