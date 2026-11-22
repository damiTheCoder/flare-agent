import { useMemo, useState } from "react";
import { Check } from "lucide-react";
import { iconSize, iconStroke } from "../icons";
import { apiPost, money, type Account, type Journal } from "../rest";
import { useApi } from "../useApi";
import { Cell, Page, PageState, Row, StatusPill, Table } from "./ui";

const field =
  "mt-1 h-9 w-full rounded-md border border-neutral-200 bg-white px-2.5 text-[12.5px] text-neutral-800 transition-colors placeholder:text-neutral-300 hover:border-neutral-300 focus:border-neutral-400 focus:outline-none focus:ring-2 focus:ring-neutral-900/10";
const label = "text-[10.5px] font-medium uppercase tracking-[0.05em] text-neutral-500";

export function ManualJournalPage() {
  const accounts = useApi<{ accounts: Account[]; count: number }>("/api/accounts");
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [memo, setMemo] = useState("");
  const [debitAccountId, setDebitAccountId] = useState("");
  const [creditAccountId, setCreditAccountId] = useState("");
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Journal | null>(null);
  const [error, setError] = useState<string | null>(null);

  const options = useMemo(() => accounts.data?.accounts ?? [], [accounts.data]);
  const canSubmit =
    !busy &&
    debitAccountId !== "" &&
    creditAccountId !== "" &&
    amount.trim() !== "" &&
    debitAccountId !== creditAccountId;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const journal = await apiPost<Journal>("/api/journals", {
        date,
        memo: memo.trim() === "" ? undefined : memo.trim(),
        debitAccountId,
        creditAccountId,
        amount: amount.trim(),
      });
      setResult(journal);
      setMemo("");
      setAmount("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not propose the journal");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Page title="Manual journal" meta="Proposals stay pending until approved">
      <PageState loading={accounts.loading} error={accounts.error}>
        <form
          className="rounded-lg border border-neutral-200 bg-white p-4"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <label className={label} htmlFor="journal-date">
                Date
              </label>
              <input
                id="journal-date"
                className={field}
                type="date"
                value={date}
                onChange={(event) => setDate(event.target.value)}
              />
            </div>
            <div>
              <label className={label} htmlFor="journal-debit">
                Debit account
              </label>
              <select
                id="journal-debit"
                className={field}
                value={debitAccountId}
                onChange={(event) => setDebitAccountId(event.target.value)}
              >
                <option value="">Select…</option>
                {options.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.code} · {account.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className={label} htmlFor="journal-credit">
                Credit account
              </label>
              <select
                id="journal-credit"
                className={field}
                value={creditAccountId}
                onChange={(event) => setCreditAccountId(event.target.value)}
              >
                <option value="">Select…</option>
                {options.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.code} · {account.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className={label} htmlFor="journal-amount">
                Amount
              </label>
              <input
                id="journal-amount"
                className={`${field} text-right tabular-nums`}
                inputMode="decimal"
                placeholder="0.00"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
              />
            </div>
          </div>

          <div className="mt-3">
            <label className={label} htmlFor="journal-memo">
              Memo
            </label>
            <input
              id="journal-memo"
              className={field}
              placeholder="What is this entry for?"
              value={memo}
              onChange={(event) => setMemo(event.target.value)}
            />
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2">
            <button
              type="submit"
              disabled={!canSubmit}
              className="h-9 rounded-md bg-neutral-900 px-3.5 text-[12.5px] font-medium text-white transition-colors hover:bg-neutral-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/25 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-neutral-300"
            >
              {busy ? "Proposing…" : "Propose journal"}
            </button>
            {debitAccountId !== "" && debitAccountId === creditAccountId ? (
              <span className="text-[11.5px] text-amber-700">Debit and credit must differ.</span>
            ) : null}
            {error !== null ? (
              <span role="alert" className="text-[11.5px] text-rose-600">
                {error}
              </span>
            ) : null}
            {result !== null ? (
              <span className="inline-flex items-center gap-1.5 text-[11.5px] text-emerald-700">
                <Check size={iconSize.sm} strokeWidth={iconStroke} aria-hidden="true" />
                Proposed {result.id} — {money(result.totalDebit)}. It is waiting in Journal Approvals.
              </span>
            ) : null}
          </div>
        </form>
      </PageState>
    </Page>
  );
}

export function ApprovalsPage() {
  const { data, error, loading, reload } = useApi<{ journals: Journal[]; count: number }>(
    "/api/journals/pending",
  );
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const approve = async (id: string) => {
    setBusy(id);
    setFailure(null);
    try {
      await apiPost<Journal>(`/api/journals/${id}/approve`, {});
      reload();
    } catch (cause) {
      setFailure(cause instanceof Error ? cause.message : "Approval failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Page title="Journal approvals" meta={data !== null ? `${data.count} pending` : undefined}>
      {failure !== null ? (
        <p role="alert" className="mb-2 text-[11.5px] text-rose-600">
          {failure}
        </p>
      ) : null}
      <PageState loading={loading} error={error} empty={data !== null && data.count === 0}>
        {data !== null ? (
          <Table
            head={
              <tr>
                <th scope="col" className="px-3 py-2 text-left font-semibold">
                  Date
                </th>
                <th scope="col" className="px-3 py-2 text-left font-semibold">
                  Memo
                </th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">
                  Amount
                </th>
                <th scope="col" className="px-3 py-2 text-left font-semibold">
                  Status
                </th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">
                  Action
                </th>
              </tr>
            }
          >
            {data.journals.map((journal) => (
              <Row key={journal.id}>
                <Cell className="whitespace-nowrap text-neutral-500">{journal.date}</Cell>
                <Cell>{journal.memo ?? "—"}</Cell>
                <Cell align="right" strong>
                  {money(journal.totalDebit)}
                </Cell>
                <Cell>
                  <StatusPill status={journal.status} />
                </Cell>
                <td className="px-3 py-1 text-right">
                  <button
                    type="button"
                    disabled={busy === journal.id}
                    onClick={() => void approve(journal.id)}
                    className="h-7 rounded-md border border-neutral-200 bg-white px-2.5 text-[11.5px] font-medium text-neutral-700 transition-colors hover:border-neutral-300 hover:bg-neutral-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/15 disabled:cursor-not-allowed disabled:text-neutral-400"
                  >
                    {busy === journal.id ? "Approving…" : "Approve"}
                  </button>
                </td>
              </Row>
            ))}
          </Table>
        ) : null}
      </PageState>
    </Page>
  );
}
