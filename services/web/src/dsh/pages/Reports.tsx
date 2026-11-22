import type { ReactNode } from "react";
import { money, type BalanceSheet, type ProfitLoss, type StatementLine } from "../rest";
import { useApi } from "../useApi";
import { Cell, Page, PageState, Row, Table } from "./ui";

function Section({ label }: { label: string }) {
  return (
    <tr className="border-t border-neutral-100 bg-neutral-50/80">
      <td colSpan={3} className="px-3 py-[5px] text-[10px] font-semibold uppercase tracking-[0.07em] text-neutral-500">
        {label}
      </td>
    </tr>
  );
}

function Lines({ lines }: { lines: StatementLine[] }) {
  if (lines.length === 0) {
    return (
      <tr className="border-t border-neutral-100">
        <td colSpan={3} className="px-3 py-[6px] text-[12px] text-neutral-400">
          No balances
        </td>
      </tr>
    );
  }
  return (
    <>
      {lines.map((line) => (
        <Row key={line.accountId}>
          <Cell className="w-16 font-mono text-[11px] text-neutral-400">{line.code}</Cell>
          <Cell>{line.name}</Cell>
          <Cell align="right">{money(line.amount)}</Cell>
        </Row>
      ))}
    </>
  );
}

function Total({ label, amount, strong = false }: { label: string; amount: string; strong?: boolean }) {
  return (
    <tr className={`border-t border-neutral-200 ${strong ? "bg-neutral-50" : ""}`}>
      <td className="px-3 py-[6px]" />
      <td className={`px-3 py-[6px] text-[12px] ${strong ? "font-semibold text-neutral-900" : "font-medium text-neutral-700"}`}>
        {label}
      </td>
      <td className={`px-3 py-[6px] text-right text-[12px] tabular-nums ${strong ? "font-semibold text-neutral-900" : "font-medium text-neutral-700"}`}>
        {money(amount)}
      </td>
    </tr>
  );
}

function StatementTable({ children }: { children: ReactNode }) {
  return (
    <Table
      head={
        <tr>
          <th className="px-3 py-1.5 text-left font-semibold">Code</th>
          <th className="px-3 py-1.5 text-left font-semibold">Line</th>
          <th className="px-3 py-1.5 text-right font-semibold">Amount</th>
        </tr>
      }
    >
      {children}
    </Table>
  );
}

export function ProfitLossPage() {
  const { data, error, loading } = useApi<ProfitLoss>("/api/reports/pl");
  const period =
    data !== null && (data.from !== null || data.to !== null)
      ? `${data.from ?? "start"} → ${data.to ?? "today"}`
      : "All time";

  return (
    <Page title="Profit & loss" meta={period}>
      <PageState loading={loading} error={error}>
        {data !== null ? (
          <>
            <div className="mb-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
              <div className="rounded-lg border border-neutral-200 bg-white px-3 py-2">
                <p className="text-[10px] font-medium uppercase tracking-[0.06em] text-neutral-400">Revenue</p>
                <p className="mt-0.5 text-[15px] font-semibold tabular-nums text-neutral-900">
                  {money(data.totalRevenue)}
                </p>
              </div>
              <div className="rounded-lg border border-neutral-200 bg-white px-3 py-2">
                <p className="text-[10px] font-medium uppercase tracking-[0.06em] text-neutral-400">Expenses</p>
                <p className="mt-0.5 text-[15px] font-semibold tabular-nums text-neutral-900">
                  {money(data.totalExpenses)}
                </p>
              </div>
              <div className="rounded-lg border border-neutral-200 bg-white px-3 py-2">
                <p className="text-[10px] font-medium uppercase tracking-[0.06em] text-neutral-400">Net income</p>
                <p
                  className={`mt-0.5 text-[15px] font-semibold tabular-nums ${
                    Number(data.netIncome) < 0 ? "text-rose-600" : "text-emerald-700"
                  }`}
                >
                  {money(data.netIncome)}
                </p>
              </div>
            </div>

            <StatementTable>
              <Section label="Revenue" />
              <Lines lines={data.revenue} />
              <Total label="Total revenue" amount={data.totalRevenue} />
              <Section label="Expenses" />
              <Lines lines={data.expenses} />
              <Total label="Total expenses" amount={data.totalExpenses} />
              <Total label="Net income" amount={data.netIncome} strong />
            </StatementTable>
          </>
        ) : null}
      </PageState>
    </Page>
  );
}

export function BalanceSheetPage() {
  const { data, error, loading } = useApi<BalanceSheet>("/api/reports/bs");

  return (
    <Page title="Balance sheet" meta={data !== null ? `As of ${data.asOf ?? "today"}` : undefined}>
      <PageState loading={loading} error={error}>
        {data !== null ? (
          <>
            <div className="mb-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
              <div className="rounded-lg border border-neutral-200 bg-white px-3 py-2">
                <p className="text-[10px] font-medium uppercase tracking-[0.06em] text-neutral-400">Total assets</p>
                <p className="mt-0.5 text-[15px] font-semibold tabular-nums text-neutral-900">
                  {money(data.totalAssets)}
                </p>
              </div>
              <div className="rounded-lg border border-neutral-200 bg-white px-3 py-2">
                <p className="text-[10px] font-medium uppercase tracking-[0.06em] text-neutral-400">Liabilities</p>
                <p className="mt-0.5 text-[15px] font-semibold tabular-nums text-neutral-900">
                  {money(data.totalLiabilities)}
                </p>
              </div>
              <div className="rounded-lg border border-neutral-200 bg-white px-3 py-2">
                <p className="text-[10px] font-medium uppercase tracking-[0.06em] text-neutral-400">Equity</p>
                <p className="mt-0.5 text-[15px] font-semibold tabular-nums text-neutral-900">
                  {money(data.totalEquity)}
                </p>
              </div>
            </div>

            <StatementTable>
              <Section label="Assets" />
              <Lines lines={data.assets} />
              <Total label="Total assets" amount={data.totalAssets} strong />
              <Section label="Liabilities" />
              <Lines lines={data.liabilities} />
              <Total label="Total liabilities" amount={data.totalLiabilities} />
              <Section label="Equity" />
              <Lines lines={data.equity} />
              <Row>
                <Cell>{""}</Cell>
                <Cell className="text-neutral-600">Current period earnings</Cell>
                <Cell align="right">{money(data.netIncome)}</Cell>
              </Row>
              <Total label="Total equity" amount={data.totalEquity} />
              <Total
                label="Total liabilities + equity"
                amount={(Number(data.totalLiabilities) + Number(data.totalEquity)).toFixed(2)}
                strong
              />
            </StatementTable>
          </>
        ) : null}
      </PageState>
    </Page>
  );
}
