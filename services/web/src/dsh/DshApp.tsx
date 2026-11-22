/** DSH-style shell: dense sidebar + chat feed + floating composer. */

import { useCallback, useEffect, useRef, useState } from "react";
import { streamChat, type ChatMessage, type ToolCallEvent, type ToolResultEvent } from "./api";
import { Composer } from "./Composer";
import { Header } from "./Header";
import { ToolCard } from "./ToolCard";

type Item = { kind: "text"; text: string } | { kind: "tool"; callId: string };
type Turn =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "assistant"; items: Item[] };
type ToolState = { call: ToolCallEvent; result?: ToolResultEvent };

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
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [model, setModel] = useState("DeepSeek V4 Flash");
  const [tokens, setTokens] = useState(0);
  const [steps, setSteps] = useState(0);
  const [tokensPerSecond, setTokensPerSecond] = useState(0);
  const feedRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const demoRan = useRef(false);
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

  useEffect(() => {
    if (demoRan.current) return;
    if (new URLSearchParams(window.location.search).get("demo") !== "invoice") return;
    demoRan.current = true;
    void send("Create an invoice for Adeshina for 2 Ankara fabric");
  }, [send]);

  const newChat = () => {
    abortRef.current?.abort();
    setTurns([]);
    setTools({});
    setDraft("");
    setStreaming(false);
    setTokens(0);
    setSteps(0);
    setTokensPerSecond(0);
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

  const firstUser = turns.find((turn) => turn.role === "user");
  const sessionTitle =
    firstUser !== undefined ? `${firstUser.text.slice(0, 34)}${firstUser.text.length > 34 ? "…" : ""}` : "New session";

  return (
    <div className="flex h-screen w-full overflow-hidden bg-white font-sans text-[13px] text-neutral-900">
      {sidebarOpen ? (
        <aside className="flex w-[250px] shrink-0 flex-col border-r border-neutral-200 bg-neutral-50/80 px-2.5 py-2.5">
          <div className="flex items-center gap-2 px-1 pb-2">
            <span className="grid h-[18px] w-[18px] place-items-center rounded-[5px] bg-blue-600 text-[10px] font-bold text-white">
              M
            </span>
            <span className="text-[12.5px] font-semibold tracking-tight">MicroBalance</span>
          </div>

          <button
            type="button"
            onClick={newChat}
            className="flex h-8 items-center justify-center gap-1.5 rounded-lg border border-neutral-200 bg-white text-[12px] font-medium text-neutral-700 shadow-sm hover:bg-neutral-50"
          >
            <span className="text-[13px] leading-none">+</span> New chat
          </button>

          <p className="mt-3 px-1.5 text-[9.5px] font-semibold uppercase tracking-[0.08em] text-neutral-400">
            Chats
          </p>
          <nav className="mt-0.5 flex flex-col gap-px">
            {turns.length === 0 ? (
              <p className="px-1.5 py-1 text-[12px] text-neutral-400">No conversations yet</p>
            ) : (
              <button
                type="button"
                className="truncate rounded-md bg-neutral-200/70 px-1.5 py-1 text-left text-[12px] text-neutral-700"
              >
                {sessionTitle}
              </button>
            )}
          </nav>

          <div className="mt-auto border-t border-neutral-200 pt-2">
            <button type="button" className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 hover:bg-neutral-200/60">
              <span className="grid h-5 w-5 place-items-center rounded-full bg-neutral-300 text-[10px] font-semibold text-white">
                D
              </span>
              <span className="text-[12px] text-neutral-700">Damian</span>
            </button>
          </div>
        </aside>
      ) : null}

      <main className="flex min-w-0 flex-1 flex-col">
        <Header
          title={sessionTitle}
          onToggleSidebar={() => setSidebarOpen((open) => !open)}
          onCopyMarkdown={copyMarkdown}
          onDownloadLog={downloadLog}
        />

        <div ref={feedRef} className="flex-1 overflow-y-auto px-6 py-4">
          <div className="mx-auto flex max-w-[760px] flex-col gap-3">
            {turns.length === 0 ? (
              <div className="pt-6">
                <p className="text-[13px] font-medium text-neutral-700">Start a task</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {SUGGESTIONS.map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      onClick={() => void send(suggestion)}
                      className="rounded-full border border-neutral-200 bg-white px-2.5 py-1 text-[11.5px] text-neutral-600 hover:bg-neutral-50"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            {turns.map((turn) =>
              turn.role === "user" ? (
                <div key={turn.id} className="ml-auto max-w-[80%] rounded-2xl bg-neutral-100 px-3 py-1.5 text-[13px] text-neutral-800">
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
                      <p key={`text-${index}`} className="whitespace-pre-wrap text-[13px] leading-6 text-neutral-800">
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
      </main>
    </div>
  );
}
