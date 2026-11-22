/** DSH-style shell for the Flare backend. */

import { useCallback, useEffect, useRef, useState } from "react";
import { streamChat, type ChatMessage, type ToolCallEvent, type ToolResultEvent } from "./api";
import { ToolCard } from "./ToolCard";
import "./dsh.css";

type Item = { kind: "text"; text: string } | { kind: "tool"; callId: string };
type Turn =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "assistant"; items: Item[] };
type ToolState = { call: ToolCallEvent; result?: ToolResultEvent };

const MODELS = ["flare-agent"];
const SUGGESTIONS = [
  "Create an invoice for Adeshina for 2 Ankara fabric",
  "Show my trial balance",
  "What is my VAT payable?",
];

let counter = 0;
const nextId = (prefix: string) => `${prefix}-${++counter}`;

function Menu({
  x,
  y,
  onClose,
}: {
  x: number;
  y: number;
  onClose: () => void;
}) {
  useEffect(() => {
    const close = () => onClose();
    window.addEventListener("click", close);
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("keydown", close);
    };
  }, [onClose]);

  return (
    <div className="context-menu" style={{ left: x, top: y }} onClick={(event) => event.stopPropagation()}>
      <button type="button" className="menu-item">
        <span>Open in</span>
        <span className="chev">›</span>
      </button>
      <div className="menu-sep" />
      <button type="button" className="menu-item">
        <span>Feedback</span>
      </button>
    </div>
  );
}

export default function DshApp() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [tools, setTools] = useState<Record<string, ToolState>>({});
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const [modelOpen, setModelOpen] = useState(false);
  const [model, setModel] = useState(MODELS[0]);
  const [tokens, setTokens] = useState(0);
  const [steps, setSteps] = useState(0);
  const feedRef = useRef<HTMLDivElement>(null);
  const demoRan = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
  }, [turns, tools]);

  const patchAssistant = useCallback((turnId: string, mutate: (items: Item[]) => Item[]) => {
    setTurns((current) =>
      current.map((turn) =>
        turn.id === turnId && turn.role === "assistant"
          ? { ...turn, items: mutate(turn.items) }
          : turn,
      ),
    );
  }, []);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (trimmed === "" || streaming) return;

      const userTurn: Turn = { id: nextId("user"), role: "user", text: trimmed };
      const assistantId = nextId("assistant");
      const assistantTurn: Turn = { id: assistantId, role: "assistant", items: [] };
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

      setTurns((current) => [...current, userTurn, assistantTurn]);
      setDraft("");
      setStreaming(true);
      const controller = new AbortController();
      abortRef.current = controller;

      await streamChat(
        history,
        {
          onContent: (delta) => {
            setTokens((value) => value + Math.max(1, Math.round(delta.length / 4)));
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
          onDone: () => setStreaming(false),
          onError: (message) => {
            patchAssistant(assistantId, (items) => [
              ...items,
              { kind: "text", text: `⚠︎ ${message}` },
            ]);
            setStreaming(false);
          },
        },
        controller.signal,
      );
      setStreaming(false);
    },
    [patchAssistant, streaming, turns],
  );

  // `?demo=invoice` drives the review/demo path: one scripted turn that shows
  // the create_invoice card from Pending to Success.
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
  };

  return (
    <div className="app" onContextMenu={(event) => event.preventDefault()}>
      <aside className="sidebar">
        <div className="brand">
          <span className="mark" aria-hidden="true" />
          <span className="brand-name">microBalance</span>
        </div>

        <button type="button" className="new-chat" onClick={newChat}>
          <span aria-hidden="true">＋</span> <span className="label">New chat</span>
        </button>

        <nav className="sessions">
          <p className="section-label">Today</p>
          {turns.length === 0 ? (
            <p className="empty-hint">No conversations yet</p>
          ) : (
            <button type="button" className="session active">
              {turns[0]?.role === "user" ? turns[0].text.slice(0, 34) : "New conversation"}
            </button>
          )}
        </nav>

        <div className="sidebar-foot">
          <button type="button" className="foot-row">
            <span className="avatar" aria-hidden="true" />
            <span className="who">Damian</span>
          </button>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <span className="topbar-title">MicroBalance</span>
          <span className="chip">agentic finance</span>
        </header>

        <div className="feed" ref={feedRef}>
          <div className="feed-inner">
            {turns.length === 0 ? (
              <section className="hero">
                <h1>What should we put on the books?</h1>
                <p>Ask for an invoice, a payment, a report — the agent calls real accounting tools.</p>
                <div className="suggestions">
                  {SUGGESTIONS.map((suggestion) => (
                    <button key={suggestion} type="button" onClick={() => void send(suggestion)}>
                      {suggestion}
                    </button>
                  ))}
                </div>
              </section>
            ) : null}

            {turns.map((turn) =>
              turn.role === "user" ? (
                <div
                  key={turn.id}
                  className="msg user"
                  onContextMenu={(event) => {
                    event.preventDefault();
                    setMenu({ x: event.clientX, y: event.clientY });
                  }}
                >
                  {turn.text}
                </div>
              ) : (
                <div key={turn.id} className="msg assistant">
                  {turn.items.map((item, index) =>
                    item.kind === "tool" ? (
                      <ToolCard
                        key={`${item.callId}-${index}`}
                        call={tools[item.callId]?.call ?? { id: item.callId, name: "tool", arguments: {} }}
                        result={tools[item.callId]?.result}
                        onContextMenu={(event) => {
                          event.preventDefault();
                          setMenu({ x: event.clientX, y: event.clientY });
                        }}
                      />
                    ) : (
                      <p key={`text-${index}`} className="assistant-text">
                        {item.text}
                      </p>
                    ),
                  )}
                  {streaming && turn.items.length === 0 ? (
                    <p className="typing" aria-label="Assistant is working">
                      <span />
                      <span />
                      <span />
                    </p>
                  ) : null}
                </div>
              ),
            )}
          </div>
        </div>

        <div className="composer-wrap">
          <div className="composer">
            <textarea
              value={draft}
              placeholder="Message MicroBalance…"
              rows={2}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void send(draft);
                }
              }}
            />
            <div className="composer-row">
              <div className="model-select">
                <button
                  type="button"
                  className="pill"
                  aria-haspopup="listbox"
                  aria-expanded={modelOpen}
                  onClick={() => setModelOpen((open) => !open)}
                >
                  <span className="dot" aria-hidden="true" />
                  {model}
                  <span aria-hidden="true">▾</span>
                </button>
                {modelOpen ? (
                  <div className="model-menu" role="listbox">
                    {MODELS.map((option) => (
                      <button
                        key={option}
                        type="button"
                        className="menu-item"
                        role="option"
                        aria-selected={option === model}
                        onClick={() => {
                          setModel(option);
                          setModelOpen(false);
                        }}
                      >
                        {option}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
              <button type="button" className="icon-btn" aria-label="Attach">
                📎
              </button>
              <button type="button" className="icon-btn" aria-label="Voice input">
                🎙
              </button>
              <button
                type="button"
                className="send-btn"
                aria-label="Send"
                disabled={streaming || draft.trim() === ""}
                onClick={() => void send(draft)}
              >
                ↑
              </button>
            </div>
          </div>
          <div className="telemetry" data-testid="telemetry">
            <span>{tokens.toLocaleString()} tokens</span>
            <span>{steps} steps</span>
            <span>cache 0%</span>
          </div>
        </div>
      </main>

      {menu !== null ? <Menu x={menu.x} y={menu.y} onClose={() => setMenu(null)} /> : null}
    </div>
  );
}
