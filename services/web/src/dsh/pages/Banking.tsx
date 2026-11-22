import { money, type BankAccount, type ReconTransaction } from "../rest";
import { useApi } from "../useApi";
import { Cell, Page, PageState, Row, StatusPill, Table } from "./ui";

export function BankAccountsPage() {
  const { data, error, loading } = useApi<{ accounts: BankAccount[]; count: number }>(
    "/api/bank-accounts",
  );
  return (
    <Page title="Bank accounts" meta={data !== null ? `${data.count}` : undefined}>
      <PageState loading={loading} error={error} empty={data !== null && data.count === 0}>
        {data !== null ? (
          <Table
            head={
              <tr>
                <th className="px-3 py-1.5 text-left font-semibold">Code</th>
                <th className="px-3 py-1.5 text-left font-semibold">Account</th>
                <th className="hidden px-3 py-1.5 text-left font-semibold sm:table-cell">Type</th>
                <th className="px-3 py-1.5 text-right font-semibold">Balance</th>
              </tr>
            }
          >
            {data.accounts.map((account) => (
              <Row key={account.id}>
                <Cell className="font-mono text-[11px] text-neutral-500">{account.code}</Cell>
                <Cell>{account.name}</Cell>
                <Cell className="hidden text-neutral-500 sm:table-cell">{account.type}</Cell>
                <Cell align="right" strong>
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

export function ReconciliationPage() {
  const { data, error, loading } = useApi<{
    transactions: ReconTransaction[];
    count: number;
    accounts: BankAccount[];
  }>("/api/reconciliation");

  return (
    <Page
      title="Reconciliation"
      meta={data !== null ? `${data.count} unreconciled · ${data.accounts.length} accounts` : undefined}
    >
      {data !== null ? (
        <div className="mb-3 flex flex-wrap gap-1.5">
          {data.accounts.map((account) => (
            <span
              key={account.id}
              className="rounded-full border border-neutral-200 bg-white px-2 py-0.5 text-[11px] text-neutral-600"
            >
              {account.name} · {money(account.balance)}
            </span>
          ))}
        </div>
      ) : null}
      <PageState loading={loading} error={error} empty={data !== null && data.count === 0}>
        {data !== null ? (
          <Table
            head={
              <tr>
                <th className="px-3 py-1.5 text-left font-semibold">Date</th>
                <th className="px-3 py-1.5 text-left font-semibold">Description</th>
                <th className="px-3 py-1.5 text-right font-semibold">Amount</th>
                <th className="px-3 py-1.5 text-left font-semibold">Type</th>
                <th className="px-3 py-1.5 text-left font-semibold">Status</th>
              </tr>
            }
          >
            {data.transactions.map((txn) => (
              <Row key={txn.id}>
                <Cell className="text-neutral-500">{txn.date}</Cell>
                <Cell>{txn.description}</Cell>
                <Cell align="right">{money(txn.amount)}</Cell>
                <Cell className="text-neutral-500">{txn.type}</Cell>
                <Cell>
                  <StatusPill status={txn.status} />
                </Cell>
              </Row>
            ))}
          </Table>
        ) : null}
      </PageState>
    </Page>
  );
}
