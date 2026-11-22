import { money, type Account } from "../rest";
import { useApi } from "../useApi";
import { Cell, Page, PageState, Row, Table } from "./ui";

export function ChartOfAccountsPage() {
  const { data, error, loading } = useApi<{ accounts: Account[]; count: number }>("/api/accounts");

  return (
    <Page title="Chart of accounts" meta={data !== null ? `${data.count} accounts` : undefined}>
      <PageState loading={loading} error={error} empty={data !== null && data.count === 0}>
        {data !== null ? (
          <Table
            head={
              <tr>
                <th className="px-3 py-1.5 text-left font-semibold">Code</th>
                <th className="px-3 py-1.5 text-left font-semibold">Name</th>
                <th className="px-3 py-1.5 text-left font-semibold">Type</th>
                <th className="hidden px-3 py-1.5 text-left font-semibold sm:table-cell">Category</th>
                <th className="px-3 py-1.5 text-right font-semibold">Balance</th>
              </tr>
            }
          >
            {data.accounts.map((account) => (
              <Row key={account.id}>
                <Cell className="font-mono text-[11px] text-neutral-500">{account.code}</Cell>
                <Cell>{account.name}</Cell>
                <Cell className="text-neutral-500">{account.type}</Cell>
                <Cell className="hidden text-neutral-500 sm:table-cell">{account.category}</Cell>
                <Cell align="right">{money(account.balance)}</Cell>
              </Row>
            ))}
          </Table>
        ) : null}
      </PageState>
    </Page>
  );
}
