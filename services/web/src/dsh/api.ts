/** SSE client for the Flare backend (OpenAI-compatible + tool events). */

// Same-origin in production (FastAPI serves the built UI) and through the Vite
// proxy in development, so no CORS configuration is involved either way.
export const CHAT_ENDPOINT = "/v1/chat/completions";

export type ChatMessage = { role: "user" | "assistant"; content: string };

export type ToolCallEvent = {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
};

export type ToolResultEvent = {
  id: string;
  ok: boolean;
  content: string;
  errorCode?: string | null;
};

export type StreamHandlers = {
  onContent: (text: string) => void;
  onToolCall: (call: ToolCallEvent) => void;
  onToolResult: (result: ToolResultEvent) => void;
  onDone: () => void;
  onError: (message: string) => void;
};

type ParsedFrame = { event: string; data: string };

function parseFrame(block: string): ParsedFrame | null {
  let event = "message";
  const data: string[] = [];
  for (const rawLine of block.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    if (line === "" || line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (data.length === 0) return null;
  return { event, data: data.join("\n") };
}

export async function streamChat(
  messages: ChatMessage[],
  handlers: StreamHandlers,
  signal?: AbortSignal,
  model: string = "flare-agent",
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(CHAT_ENDPOINT, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        model,
        stream: true,
        messages: messages.map((message) => ({ role: message.role, content: message.content })),
      }),
      signal,
    });
  } catch (cause) {
    handlers.onError(cause instanceof Error ? cause.message : "network error");
    return;
  }

  if (!response.ok || response.body === null) {
    handlers.onError(`chat request failed (${response.status})`);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const handle = (frame: ParsedFrame): boolean => {
    if (frame.data === "[DONE]") {
      handlers.onDone();
      return true;
    }
    let payload: unknown;
    try {
      payload = JSON.parse(frame.data);
    } catch {
      return false;
    }
    if (frame.event === "tool_call") {
      handlers.onToolCall(payload as ToolCallEvent);
      return false;
    }
    if (frame.event === "tool_result") {
      handlers.onToolResult(payload as ToolResultEvent);
      return false;
    }
    const chunk = payload as {
      choices?: Array<{ delta?: { content?: string } }>;
    };
    const text = chunk.choices?.[0]?.delta?.content;
    if (typeof text === "string" && text !== "") handlers.onContent(text);
    return false;
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let split = buffer.indexOf("\n\n");
    while (split >= 0) {
      const block = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      const frame = parseFrame(block);
      if (frame !== null && handle(frame)) return;
      split = buffer.indexOf("\n\n");
    }
  }
  handlers.onDone();
}
