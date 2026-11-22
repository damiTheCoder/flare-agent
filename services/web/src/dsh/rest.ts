/** Typed access to the ERP REST surface (same origin as the SPA). */

export type TrialBalanceRow = {
  id: string;
  code: string;
  name: string;
  type: string;
  category: string;
  isSystem: boolean;
  debit: string;
  credit: string;
  balance: string;
};

export type TrialBalance = {
  accounts: TrialBalanceRow[];
  totalDebit: string;
  totalCredit: string;
};

export type Account = TrialBalanceRow;

export type Invoice = {
  id: string;
  invoiceNumber: string;
  customer: string | null;
  date: string;
  dueDate: string;
  status: string;
  total: string;
  amountPaid: string;
  outstanding: string;
};

export type Bill = {
  id: string;
  billNumber: string;
  vendor: string | null;
  date: string;
  dueDate: string;
  status: string;
  total: string;
  netPayable: string;
  amountPaid: string;
  outstanding: string;
};

export type Summary = {
  totalRevenue: string;
  totalExpenses: string;
  netIncome: string;
  cash: string;
  bank: string;
  receivables: string;
  payables: string;
  arOutstanding: string;
  apOutstanding: string;
  invoiceCount: number;
};

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { accept: "application/json" } });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: { message?: string } | string };
      if (typeof body.detail === "string") message = body.detail;
      else if (body.detail?.message !== undefined) message = body.detail.message;
    } catch {
      // keep the HTTP status text
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function money(value: string | number | undefined): string {
  if (value === undefined || value === "") return "—";
  const amount = Number(value);
  if (Number.isNaN(amount)) return String(value);
  return `₦${amount.toLocaleString("en-NG", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}


export type Customer = { id: string; name: string; email: string | null; phone: string | null };
export type Vendor = Customer;

export type Employee = {
  id: string;
  name: string;
  email: string | null;
  basicSalary: string;
  housingAllowance: string;
  transportAllowance: string;
  grossSalary: string;
  isActive: boolean;
};

export type PayrollRun = {
  id: string;
  month: string;
  year: number;
  status: string;
  totalGross: string;
  totalNet: string;
  totalPaye: string;
  totalPension: string;
  totalNhf: string;
};

export type AgingRow = {
  bucket: string;
  daysPastDue: number;
  dueDate?: string;
  invoiceId?: string;
  billId?: string;
  invoiceNumber?: string;
  billNumber?: string;
  customer?: string | null;
  vendor?: string | null;
  outstanding: string;
};

export type Aging = {
  asOf: string;
  buckets: Array<{ key: string; label: string; count: number; total: string }>;
  totalOutstanding: string;
  invoices?: AgingRow[];
  bills?: AgingRow[];
};

export type StatementLine = {
  accountId: string;
  code: string;
  name: string;
  type?: string;
  amount: string;
};

export type ProfitLoss = {
  from: string | null;
  to: string | null;
  revenue: StatementLine[];
  expenses: StatementLine[];
  totalRevenue: string;
  totalExpenses: string;
  netIncome: string;
};

export type BalanceSheet = {
  asOf: string | null;
  assets: StatementLine[];
  liabilities: StatementLine[];
  equity: StatementLine[];
  totalAssets: string;
  totalLiabilities: string;
  totalEquity: string;
  netIncome: string;
};

export type TaxSummary = { vatPayable: string; whtPayable: string };
export type BankAccount = { id: string; code: string; name: string; type: string; balance: string };

export type ReconTransaction = {
  id: string;
  date: string;
  description: string;
  amount: string;
  type: string;
  status: string;
};

export type Journal = {
  id: string;
  date: string;
  memo: string | null;
  status: string;
  totalDebit: string;
  totalCredit: string;
  requiresApproval: boolean;
};

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const parsed = (await response.json()) as { detail?: { message?: string } | string };
      if (typeof parsed.detail === "string") message = parsed.detail;
      else if (parsed.detail?.message !== undefined) message = parsed.detail.message;
    } catch {
      // keep status text
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}
