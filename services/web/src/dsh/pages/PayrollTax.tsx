import { money, type Employee, type PayrollRun, type TaxSummary } from "../rest";
import { useApi } from "../useApi";
import { Cell, Page, PageState, Row, StatusPill, Table } from "./ui";

export function EmployeesPage() {
  const { data, error, loading } = useApi<{ employees: Employee[]; count: number }>("/api/employees");

  return (
    <Page title="Employees" meta={data !== null ? `${data.count}` : undefined}>
      <PageState loading={loading} error={error} empty={data !== null && data.count === 0}>
        {data !== null ? (
          <Table
            head={
              <tr>
                <th scope="col" className="px-3 py-2 text-left font-semibold">Name</th>
                <th scope="col" className="hidden px-3 py-2 text-left font-semibold sm:table-cell">Email</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Basic</th>
                <th scope="col" className="hidden px-3 py-2 text-right font-semibold md:table-cell">Housing</th>
                <th scope="col" className="hidden px-3 py-2 text-right font-semibold md:table-cell">Transport</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Gross</th>
                <th scope="col" className="px-3 py-2 text-left font-semibold">Active</th>
              </tr>
            }
          >
            {data.employees.map((employee) => (
              <Row key={employee.id}>
                <Cell>{employee.name}</Cell>
                <Cell className="hidden text-neutral-500 sm:table-cell">{employee.email ?? "—"}</Cell>
                <Cell align="right">{money(employee.basicSalary)}</Cell>
                <Cell align="right" className="hidden md:table-cell">
                  {money(employee.housingAllowance)}
                </Cell>
                <Cell align="right" className="hidden md:table-cell">
                  {money(employee.transportAllowance)}
                </Cell>
                <Cell align="right" strong>
                  {money(employee.grossSalary)}
                </Cell>
                <Cell>
                  <StatusPill status={employee.isActive ? "ACTIVE" : "INACTIVE"} />
                </Cell>
              </Row>
            ))}
          </Table>
        ) : null}
      </PageState>
    </Page>
  );
}

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

function period(run: PayrollRun): string {
  const index = Number(run.month);
  return index >= 1 && index <= 12 ? `${MONTHS[index - 1]} ${run.year}` : `${run.month} ${run.year}`;
}

export function PayrollHistoryPage() {
  const { data, error, loading } = useApi<{ runs: PayrollRun[]; count: number }>("/api/payroll/history");

  return (
    <Page title="Payroll history" meta={data !== null ? `${data.count} runs` : undefined}>
      <PageState loading={loading} error={error} empty={data !== null && data.count === 0}>
        {data !== null ? (
          <Table
            head={
              <tr>
                <th scope="col" className="px-3 py-2 text-left font-semibold">Period</th>
                <th scope="col" className="px-3 py-2 text-left font-semibold">Status</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Gross</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Net</th>
                <th scope="col" className="hidden px-3 py-2 text-right font-semibold sm:table-cell">PAYE</th>
                <th scope="col" className="hidden px-3 py-2 text-right font-semibold md:table-cell">Pension</th>
                <th scope="col" className="hidden px-3 py-2 text-right font-semibold md:table-cell">NHF</th>
              </tr>
            }
          >
            {data.runs.map((run) => (
              <Row key={run.id}>
                <Cell>{period(run)}</Cell>
                <Cell>
                  <StatusPill status={run.status} />
                </Cell>
                <Cell align="right">{money(run.totalGross)}</Cell>
                <Cell align="right" strong>
                  {money(run.totalNet)}
                </Cell>
                <Cell align="right" className="hidden sm:table-cell">
                  {money(run.totalPaye)}
                </Cell>
                <Cell align="right" className="hidden md:table-cell">
                  {money(run.totalPension)}
                </Cell>
                <Cell align="right" className="hidden md:table-cell">
                  {money(run.totalNhf)}
                </Cell>
              </Row>
            ))}
          </Table>
        ) : null}
      </PageState>
    </Page>
  );
}

export function TaxSummaryPage() {
  const { data, error, loading } = useApi<TaxSummary>("/api/tax/summary");

  return (
    <Page title="Tax summary">
      <PageState loading={loading} error={error}>
        {data !== null ? (
          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
            <div className="rounded-lg border border-neutral-200 bg-white px-3.5 py-3">
              <p className="text-[10.5px] font-medium uppercase tracking-[0.06em] text-neutral-400">
                VAT payable
              </p>
              <p className="mt-1 text-[18px] font-semibold leading-none tabular-nums text-neutral-900">
                {money(data.vatPayable)}
              </p>
              <p className="mt-1 text-[11px] text-neutral-400">Output VAT less input VAT</p>
            </div>
            <div className="rounded-lg border border-neutral-200 bg-white px-3.5 py-3">
              <p className="text-[10.5px] font-medium uppercase tracking-[0.06em] text-neutral-400">
                WHT payable
              </p>
              <p className="mt-1 text-[18px] font-semibold leading-none tabular-nums text-neutral-900">
                {money(data.whtPayable)}
              </p>
              <p className="mt-1 text-[11px] text-neutral-400">Deducted from vendor payments</p>
            </div>
            <div className="rounded-lg border border-neutral-300 bg-neutral-50 px-3.5 py-3">
              <p className="text-[10.5px] font-medium uppercase tracking-[0.06em] text-neutral-500">
                Total tax due
              </p>
              <p className="mt-1 text-[18px] font-semibold leading-none tabular-nums text-neutral-900">
                {money(Number(data.vatPayable) + Number(data.whtPayable))}
              </p>
              <p className="mt-1 text-[11px] text-neutral-400">VAT plus withholding tax</p>
            </div>
          </div>
        ) : null}
      </PageState>
    </Page>
  );
}
