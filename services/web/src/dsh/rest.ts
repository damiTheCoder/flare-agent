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
