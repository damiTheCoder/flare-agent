import { useMemo, useState } from "react";
import { apiPost, money, type Account, type Journal } from "../rest";
import { useApi } from "../useApi";
import { Cell, Page, PageState, Row, StatusPill, Table } from "./ui";

const field = "h-7 w-full rounded-md border border-neutral-200 bg-white px-2 text-[12px] text-neutral-800 focus:border-neutral-400 focus:outline-none";
const label = "text-[9.5px] font-semibold uppercase tracking-[0.06em] text-neutral-400";

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
    !busy && debitAccountId !== "" && creditAccountId !== "" && amount.trim() !== "" && debitAccountId !== creditAccountId;

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
    <Page title="Manual journal" meta="Proposals stay PENDING until approved">
      <PageState loading={accounts.loading} error={accounts.error}>
        <form
          className="rounded-lg border border-neutral-200 bg-white p-3"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <p className={label}>Date</p>
              <input className={`${field} mt-0.5`} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </div>
            <div>
              <p className={label}>Debit account</p>
              <select
                className={`${field} mt-0.5`}
                value={debitAccountId}
                onChange={(e) => setDebitAccountId(e.target.value)}
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
              <p className={label}>Credit account</p>
              <select
                className={`${field} mt-0.5`}
                value={creditAccountId}
                onChange={(e) => setCreditAccountId(e.target.value)}
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
              <p className={label}>Amount</p>
              <input
                className={`${field} mt-0.5 text-right tabular-nums`}
                inputMode="decimal"
                placeholder="0.00"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
              />
            </div>
          </div>

          <div className="mt-2">
            <p className={label}>Memo</p>
            <input
              className={`${field} mt-0.5`}
              placeholder="What is this entry for?"
              value={memo}
              onChange={(e) => setMemo(e.target.value)}
            />
          </div>

          <div className="mt-3 flex items-center gap-2">
            <button
              type="submit"
              disabled={!canSubmit}
              className="rounded-md bg-neutral-900 px-3 py-1.5 text-[12px] font-medium text-white disabled:bg-neutral-300"
            >
              {busy ? "Proposing…" : "Propose journal"}
            </button>
            {debitAccountId !== "" && debitAccountId === creditAccountId ? (
              <span className="text-[11px] text-amber-600">Debit and credit must differ.</span>
            ) : null}
            {error !== null ? <span className="text-[11px] text-rose-600">{error}</span> : null}
            {result !== null ? (
              <span className="text-[11px] text-emerald-700">
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
      {failure !== null ? <p className="mb-2 text-[11px] text-rose-600">{failure}</p> : null}
      <PageState loading={loading} error={error} empty={data !== null && data.count === 0}>
        {data !== null ? (
          <Table
            head={
              <tr>
                <th className="px-3 py-1.5 text-left font-semibold">Date</th>
                <th className="px-3 py-1.5 text-left font-semibold">Memo</th>
                <th className="px-3 py-1.5 text-right font-semibold">Amount</th>
                <th className="px-3 py-1.5 text-left font-semibold">Status</th>
                <th className="px-3 py-1.5 text-right font-semibold">Action</th>
              </tr>
            }
          >
            {data.journals.map((journal) => (
              <Row key={journal.id}>
                <Cell className="text-neutral-500">{journal.date}</Cell>
                <Cell>{journal.memo ?? "—"}</Cell>
                <Cell align="right" strong>
                  {money(journal.totalDebit)}
                </Cell>
                <Cell>
                  <StatusPill status={journal.status} />
                </Cell>
                <Cell align="right">
                  <button
                    type="button"
                    disabled={busy === journal.id}
                    onClick={() => void approve(journal.id)}
                    className="rounded-md border border-neutral-200 bg-white px-2 py-0.5 text-[11px] font-medium text-neutral-700 hover:bg-neutral-50 disabled:text-neutral-400"
                  >
                    {busy === journal.id ? "Approving…" : "Approve"}
                  </button>
                </Cell>
              </Row>
            ))}
          </Table>
        ) : null}
      </PageState>
    </Page>
  );
}
