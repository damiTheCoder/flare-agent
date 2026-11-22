/** DSH-style shell: dense sidebar + chat feed + floating composer. */

import { useCallback, useEffect, useRef, useState } from "react";
import { Plus, X } from "lucide-react";
import { streamChat, type ChatMessage, type ToolCallEvent, type ToolResultEvent } from "./api";
import { apiGet } from "./rest";
import { Composer } from "./Composer";
import { Header } from "./Header";
import { ChartOfAccountsPage } from "./pages/Accounts";
import { ApAgingPage, ArAgingPage } from "./pages/Aging";
import { BankAccountsPage, ReconciliationPage } from "./pages/Banking";
import { CustomersPage, VendorsPage } from "./pages/Contacts";
import { DashboardPage } from "./pages/Dashboard";
import { ApprovalsPage, ManualJournalPage } from "./pages/Journals";
import { EmployeesPage, PayrollHistoryPage, TaxSummaryPage } from "./pages/PayrollTax";
import { BalanceSheetPage, ProfitLossPage } from "./pages/Reports";
import { PurchasesPage, SalesPage } from "./pages/Sales";
import { TrialBalancePage } from "./pages/TrialBalance";
import { iconSize, iconStroke, navIcons, navImages, type View } from "./icons";
import { ToolCard } from "./ToolCard";

type Item = { kind: "text"; text: string } | { kind: "tool"; callId: string };
type Turn =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "assistant"; items: Item[] };
type ToolState = { call: ToolCallEvent; result?: ToolResultEvent };

type NavItem = { key: View; label: string };

const NAV_GROUPS: Array<{ label: string | null; items: NavItem[] }> = [
  { label: null, items: [{ key: "dashboard", label: "Dashboard" }] },
  {
    label: "GENERAL LEDGER",
    items: [
      { key: "accounts", label: "Chart of Accounts" },
      { key: "manual-journal", label: "Manual Journal" },
      { key: "approvals", label: "Journal Approvals" },
      { key: "trial-balance", label: "Trial Balance" },
    ],
  },
  {
    label: "SALES & RECEIVABLES",
    items: [
      { key: "invoices", label: "Invoices" },
      { key: "customers", label: "Customers" },
      { key: "ar-aging", label: "AR Aging" },
    ],
  },
  {
    label: "BANKING",
    items: [
      { key: "bank-accounts", label: "Bank Accounts" },
      { key: "reconciliation", label: "Reconciliation" },
    ],
  },
  {
    label: "PURCHASES & PAYABLES",
    items: [
      { key: "bills", label: "Bills" },
      { key: "vendors", label: "Vendors" },
      { key: "ap-aging", label: "AP Aging" },
    ],
  },
  {
    label: "PAYROLL & TAX",
    items: [
      { key: "employees", label: "Employees" },
      { key: "payroll-history", label: "Payroll History" },
      { key: "tax-summary", label: "Tax Summary" },
    ],
  },
  {
    label: "REPORTS",
    items: [
      { key: "profit-loss", label: "Profit & Loss" },
      { key: "balance-sheet", label: "Balance Sheet" },
    ],
  },
];

const NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((group) => group.items);

function renderPage(view: View) {
  switch (view) {
    case "dashboard":
      return <DashboardPage />;
    case "accounts":
      return <ChartOfAccountsPage />;
    case "manual-journal":
      return <ManualJournalPage />;
    case "approvals":
      return <ApprovalsPage />;
    case "trial-balance":
      return <TrialBalancePage />;
    case "invoices":
      return <SalesPage />;
    case "customers":
      return <CustomersPage />;
    case "ar-aging":
      return <ArAgingPage />;
    case "bank-accounts":
      return <BankAccountsPage />;
    case "reconciliation":
      return <ReconciliationPage />;
    case "bills":
      return <PurchasesPage />;
    case "vendors":
      return <VendorsPage />;
    case "ap-aging":
      return <ApAgingPage />;
    case "employees":
      return <EmployeesPage />;
    case "payroll-history":
      return <PayrollHistoryPage />;
    case "tax-summary":
      return <TaxSummaryPage />;
    case "profit-loss":
      return <ProfitLossPage />;
    case "balance-sheet":
      return <BalanceSheetPage />;
    default:
      return null;
  }
}

const SUGGESTIONS = [
  "Create an invoice for Adeshina for 2 Ankara fabric",
  "Show my trial balance",
  "What is my VAT payable?",
];

let counter = 0;
const nextId = (prefix: string) => `${prefix}-${++counter}`;

export default function DshApp() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [tools, setTools] = useState<Record<string, ToolState>>({});
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [view, setView] = useState<View>("chat");
  const [sidebarOpen, setSidebarOpen] = useState(
    () => typeof window !== "undefined" && window.innerWidth >= 1024,
  );
  const [model, setModel] = useState("DeepSeek V4 Flash");
  const [tokens, setTokens] = useState(0);
  const [steps, setSteps] = useState(0);
  const [tokensPerSecond, setTokensPerSecond] = useState(0);
  const feedRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const stats = useRef({ started: 0, tokens: 0 });

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight });
  }, [turns, tools]);

  const patchAssistant = useCallback((turnId: string, mutate: (items: Item[]) => Item[]) => {
    setTurns((current) =>
      current.map((turn) =>
        turn.id === turnId && turn.role === "assistant" ? { ...turn, items: mutate(turn.items) } : turn,
      ),
    );
  }, []);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (trimmed === "" || streaming) return;

      const userTurn: Turn = { id: nextId("user"), role: "user", text: trimmed };
      const assistantId = nextId("assistant");
      const history: ChatMessage[] = [
        ...turns.flatMap((turn): ChatMessage[] =>
          turn.role === "user"
            ? [{ role: "user", content: turn.text }]
            : [
                {
                  role: "assistant",
                  content: turn.items
                    .filter((item): item is { kind: "text"; text: string } => item.kind === "text")
                    .map((item) => item.text)
                    .join(""),
                },
              ],
        ),
        { role: "user", content: trimmed },
      ];

      setTurns((current) => [...current, userTurn, { id: assistantId, role: "assistant", items: [] }]);
      setDraft("");
      if (window.innerWidth < 1024) setSidebarOpen(false);
      setStreaming(true);
      stats.current = { started: performance.now(), tokens: 0 };
      const controller = new AbortController();
      abortRef.current = controller;

      await streamChat(
        history,
        {
          onContent: (delta) => {
            stats.current.tokens += Math.max(1, Math.round(delta.length / 4));
            setTokens(stats.current.tokens);
            patchAssistant(assistantId, (items) => {
              const last = items[items.length - 1];
              if (last !== undefined && last.kind === "text") {
                return [...items.slice(0, -1), { kind: "text", text: last.text + delta }];
              }
              return [...items, { kind: "text", text: delta }];
            });
          },
          onToolCall: (call) => {
            setSteps((value) => value + 1);
            setTools((current) => ({ ...current, [call.id]: { call } }));
            patchAssistant(assistantId, (items) => [...items, { kind: "tool", callId: call.id }]);
          },
          onToolResult: (result) => {
            setTools((current) => {
              const existing = current[result.id];
              return existing === undefined ? current : { ...current, [result.id]: { ...existing, result } };
            });
          },
          onDone: () => {
            const seconds = (performance.now() - stats.current.started) / 1000;
            if (stats.current.tokens > 0 && seconds > 0) {
              setTokensPerSecond(Math.round(stats.current.tokens / seconds));
            }
            setStreaming(false);
          },
          onError: (message) => {
            patchAssistant(assistantId, (items) => [...items, { kind: "text", text: `⚠︎ ${message}` }]);
            setStreaming(false);
          },
        },
        controller.signal,
        model,
      );
      setStreaming(false);
    },
    [patchAssistant, streaming, turns, model],
  );

  const selectView = (next: View) => {
    setView(next);
    if (window.innerWidth < 1024) setSidebarOpen(false);
  };

  const newChat = () => {
    abortRef.current?.abort();
    setTurns([]);
    setTools({});
    setDraft("");
    setStreaming(false);
    setTokens(0);
    setSteps(0);
    setTokensPerSecond(0);
    setView("chat");
    if (window.innerWidth < 1024) setSidebarOpen(false);
  };

  const transcript = () => {
    const lines: string[] = ["# MicroBalance session", ""];
    for (const turn of turns) {
      if (turn.role === "user") {
        lines.push(`## You`, "", turn.text, "");
      } else {
        lines.push(`## MicroBalance`, "");
        for (const item of turn.items) {
          if (item.kind === "text") lines.push(item.text);
          else {
            const tool = tools[item.callId];
            lines.push(
              `- tool \`${tool?.call.name ?? "tool"}\` ${tool?.result === undefined ? "(pending)" : tool.result.ok ? "(success)" : "(error)"}`,
            );
            if (tool?.result !== undefined) lines.push("```", tool.result.content, "```");
          }
        }
        lines.push("");
      }
    }
    return lines.join("\n");
  };

  const copyMarkdown = () => {
    void navigator.clipboard.writeText(transcript());
  };

  const downloadLog = () => {
    const blob = new Blob([transcript()], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "microbalance-session.md";
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const [pendingCount, setPendingCount] = useState(0);
  useEffect(() => {
    let alive = true;
    apiGet<{ count: number }>("/api/journals/pending")
      .then((data) => {
        if (alive) setPendingCount(data.count);
      })
      .catch(() => {
        /* the badge is optional; a failed count must not break navigation */
      });
    return () => {
      alive = false;
    };
  }, [view]);

  const activeNavRef = useRef<HTMLButtonElement | null>(null);
  const navScrollRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const scroller = navScrollRef.current;
    if (scroller === null) return;
    // The rail keeps a stable icon order; the labelled list follows the active item.
    if (!sidebarOpen) {
      scroller.scrollTop = 0;
      return;
    }
    activeNavRef.current?.scrollIntoView({ block: "nearest" });
  }, [view, sidebarOpen]);

  const renderNavItem = (item: NavItem) => {
    const Icon = navIcons[item.key];
    const mark = navImages[item.key];
    const active = view === item.key;
    return (
      <button
        key={item.key}
        ref={active ? activeNavRef : undefined}
        type="button"
        onClick={() => selectView(item.key)}
        aria-current={active ? "page" : undefined}
        aria-label={sidebarOpen ? undefined : item.label}
        title={sidebarOpen ? undefined : item.label}
        className={
          sidebarOpen
            ? `group flex h-11 w-full items-center gap-2 rounded-md pl-2.5 pr-1.5 text-left text-[13px] transition-colors focus-visible:outline-none lg:h-9 focus-visible:ring-2 focus-visible:ring-neutral-900/15 ${
                active
                  ? "bg-neutral-200/80 font-medium text-neutral-900"
                  : "text-neutral-600 hover:bg-neutral-200/50 hover:text-neutral-900"
              }`
            : `grid h-10 w-10 place-items-center rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/15 ${
                active
                  ? "bg-neutral-200/80 text-neutral-900"
                  : "text-neutral-400 hover:bg-neutral-200/50 hover:text-neutral-600"
              }`
        }
      >
        <span
          className={
            sidebarOpen ? "flex w-5 shrink-0 justify-center" : "flex justify-center"
          }
        >
          {mark !== undefined ? (
            <img
              src={mark}
              alt=""
              aria-hidden="true"
              className="h-5 w-5 rounded-md object-cover"
            />
          ) : (
            <Icon
              size={iconSize.lg}
              strokeWidth={iconStroke}
              aria-hidden="true"
              className={
                active
                  ? "text-neutral-700"
                  : "text-neutral-400 group-hover:text-neutral-600"
              }
            />
          )}
        </span>
        {sidebarOpen ? <span className="truncate">{item.label}</span> : null}
        {sidebarOpen && item.key === "approvals" && pendingCount > 0 ? (
          <span className="ml-auto inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-md bg-amber-100 px-1 text-[10.5px] font-semibold tabular-nums text-amber-700">
            {pendingCount}
          </span>
        ) : null}
      </button>
    );
  };

  const firstUser = turns.find((turn) => turn.role === "user");
  const sessionTitle =
    firstUser !== undefined ? `${firstUser.text.slice(0, 34)}${firstUser.text.length > 34 ? "…" : ""}` : "New session";

  return (
    <div className="flex h-screen w-full overflow-hidden bg-white font-sans text-[13px] text-neutral-900">
      {sidebarOpen ? (
        <button
          type="button"
          aria-label="Close sidebar"
          onClick={() => setSidebarOpen(false)}
          className="fixed inset-0 z-20 bg-black/20 lg:hidden"
        />
      ) : null}
      <aside
        className={
          sidebarOpen
            ? "fixed inset-y-0 left-0 z-30 flex w-[240px] flex-col bg-white lg:static lg:z-auto"
            : "hidden bg-white lg:flex lg:w-16 lg:flex-col"
        }
      >
        {sidebarOpen ? (
          <div className="flex h-12 shrink-0 items-center gap-2 px-3">
            <img
              src="/logo.png"
              alt=""
              aria-hidden="true"
              className="h-6 w-9 rounded-md object-cover"
            />
            <span className="text-[14px] font-semibold tracking-tight text-neutral-900">MicroBalance</span>
            <button
              type="button"
              aria-label="Close navigation"
              onClick={() => setSidebarOpen(false)}
              className="ml-auto grid h-10 w-10 place-items-center rounded-md text-neutral-500 transition-colors hover:bg-neutral-200/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/15 lg:hidden"
            >
              <X size={iconSize.md} strokeWidth={iconStroke} aria-hidden="true" />
            </button>
          </div>
        ) : (
          <div className="flex h-12 shrink-0 items-center justify-center">
            <img
              src="/logo.png"
              alt=""
              aria-hidden="true"
              className="h-6 w-9 rounded-md object-cover"
            />
          </div>
        )}

        <div className={sidebarOpen ? "shrink-0 px-3 pb-2" : "shrink-0 pb-2"}>
          {sidebarOpen ? (
            <button
              type="button"
              onClick={newChat}
              className="flex h-10 w-full items-center gap-2 rounded-md bg-neutral-100 px-2.5 text-left text-[13px] font-medium text-neutral-800 transition-colors hover:bg-neutral-200/70 lg:h-9 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/15"
            >
              <span className="flex w-5 shrink-0 justify-center">
                <Plus size={iconSize.md} strokeWidth={iconStroke} aria-hidden="true" />
              </span>
              New chat
            </button>
          ) : (
            <button
              type="button"
              onClick={newChat}
              aria-label="New chat"
              title="New chat"
              className="mx-auto grid h-10 w-10 place-items-center rounded-md bg-neutral-100 transition-colors hover:bg-neutral-200/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/15"
            >
              <Plus size={iconSize.lg} strokeWidth={iconStroke} aria-hidden="true" />
            </button>
          )}
        </div>

        <nav
          className={
            sidebarOpen ? "mb-1 flex flex-col px-3" : "mb-1 flex flex-col items-center gap-0.5"
          }
        >
          {renderNavItem({ key: "chat", label: "Chat" })}
        </nav>

        <div className="relative flex min-h-0 flex-1 flex-col">
          <div
            ref={navScrollRef}
            className={`flex-1 overflow-y-auto px-3 ${sidebarOpen ? "pb-3" : "pb-1"}`}
          >
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 top-0 z-10 h-3 bg-gradient-to-b from-white to-transparent"
            />
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-3 bg-gradient-to-t from-white to-transparent"
            />
          <div className={sidebarOpen ? "mt-1" : "mt-0"}>
            {NAV_GROUPS.map((group, index) => (
              <div
                key={group.label ?? `standalone-${index}`}
                className={index === 0 ? "" : sidebarOpen ? "mt-3" : "mt-2"}
              >
                {sidebarOpen && group.label !== null ? (
                  <p className="px-2 pb-2 text-[11px] font-medium uppercase tracking-[0.04em] text-neutral-400">
                    {group.label}
                  </p>
                ) : null}
                <nav
                  className={
                    sidebarOpen ? "flex flex-col" : "flex flex-col items-center gap-0.5"
                  }
                >
                  {group.items.map((item) => renderNavItem(item))}
                </nav>
              </div>
            ))}
          </div>

          {sidebarOpen && turns.length > 0 ? (
            <>
              <p className="mt-5 px-2 pb-2 text-[11px] font-medium uppercase tracking-[0.04em] text-neutral-400">
                Chats
              </p>
              <nav className="flex flex-col gap-0.5">
                <button
                  type="button"
                  className="flex h-9 w-full items-center rounded-md bg-neutral-200/70 px-2.5 text-left text-[13px] text-neutral-700 transition-colors hover:bg-neutral-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/15"
                >
                  <span className="truncate">{sessionTitle}</span>
                </button>
              </nav>
            </>
          ) : null}
          </div>

        </div>

        <div className="shrink-0 p-2">
          <button
            type="button"
            aria-label={sidebarOpen ? undefined : "Account: Damian"}
            title={sidebarOpen ? undefined : "Damian"}
            className={
              sidebarOpen
                ? "flex h-11 w-full items-center gap-2.5 rounded-md px-1.5 transition-colors hover:bg-neutral-200/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/15"
                : "mx-auto grid h-10 w-10 place-items-center rounded-full transition-colors hover:bg-neutral-200/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/15"
            }
          >
            <span className="grid h-7 w-7 place-items-center rounded-full bg-neutral-300 text-[11px] font-semibold text-white">
              D
            </span>
            {sidebarOpen ? <span className="text-[13px] text-neutral-700">Damian</span> : null}
          </button>
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <Header
          title={view === "chat" ? sessionTitle : (NAV_ITEMS.find((item) => item.key === view)?.label ?? "")}
          onToggleSidebar={() => setSidebarOpen((open) => !open)}
          onCopyMarkdown={copyMarkdown}
          onDownloadLog={downloadLog}
        />

        {view === "chat" ? (
        <>
        <div ref={feedRef} className="flex-1 overflow-y-auto px-3 py-3 sm:px-5 sm:py-4 lg:px-6">
          <div className="mx-auto flex max-w-[760px] flex-col gap-3">
            {turns.length === 0 ? (
              <div className="pt-8">
                <p className="text-[13.5px] font-medium text-neutral-800">Start a task</p>
                <div className="mt-2.5 flex flex-wrap gap-2">
                  {SUGGESTIONS.map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      onClick={() => void send(suggestion)}
                      className="rounded-full border border-neutral-200 bg-white px-3 py-1.5 text-[12px] text-neutral-600 transition-colors hover:border-neutral-300 hover:bg-neutral-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/15"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            {turns.map((turn) =>
              turn.role === "user" ? (
                <div key={turn.id} className="ml-auto max-w-[80%] rounded-2xl bg-neutral-100 px-3.5 py-2 text-[13.5px] leading-6 text-neutral-800">
                  {turn.text}
                </div>
              ) : (
                <div key={turn.id} className="flex flex-col gap-2">
                  {turn.items.map((item, index) =>
                    item.kind === "tool" ? (
                      <ToolCard
                        key={`${item.callId}-${index}`}
                        call={tools[item.callId]?.call ?? { id: item.callId, name: "tool", arguments: {} }}
                        result={tools[item.callId]?.result}
                      />
                    ) : (
                      <p key={`text-${index}`} className="whitespace-pre-wrap text-[13.5px] leading-6 text-neutral-800">
                        {item.text}
                      </p>
                    ),
                  )}
                  {streaming && turn.items.length === 0 ? (
                    <p className="flex gap-1" aria-label="Assistant is working">
                      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-neutral-300" />
                      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-neutral-300 [animation-delay:150ms]" />
                      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-neutral-300 [animation-delay:300ms]" />
                    </p>
                  ) : null}
                </div>
              ),
            )}
          </div>
        </div>

        <Composer
          value={draft}
          onChange={setDraft}
          onSend={() => void send(draft)}
          streaming={streaming}
          model={model}
          onModel={setModel}
          turns={turns.filter((turn) => turn.role === "user").length}
          steps={steps}
          tokens={tokens}
          tokensPerSecond={tokensPerSecond}
          cacheHit={0}
          contextUsed={Math.min(100, Math.round((tokens / 128000) * 100))}
        />
        </>
        ) : (
          <div className="flex-1 overflow-y-auto px-3 py-4 pb-8 sm:px-5 sm:py-5 lg:px-6">
            {renderPage(view)}
          </div>
        )}

        {view !== "chat" ? (
          <button
            type="button"
            onClick={() => selectView("chat")}
            className="fixed bottom-4 right-4 z-20 h-9 rounded-full bg-neutral-900 px-3.5 text-[12.5px] font-medium text-white shadow-[0_6px_20px_rgba(16,16,20,0.18)] transition-colors hover:bg-neutral-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/25 focus-visible:ring-offset-2 lg:hidden"
          >
            Chat
          </button>
        ) : null}
      </main>
    </div>
  );
}
