/** DSH composer: one compact floating pill plus a tiny telemetry line. */

import { useState } from "react";
import { ArrowUp, Check, ChevronDown, Mic, Plug, Plus } from "lucide-react";
import { iconSize, iconStroke } from "./icons";

type Props = {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  streaming: boolean;
  model: string;
  onModel: (model: string) => void;
  turns: number;
  steps: number;
  tokens: number;
  tokensPerSecond: number;
  cacheHit: number;
  contextUsed: number;
};

const MODELS = ["DeepSeek V4 Flash", "DeepSeek V4", "flare-agent"];
const INTEGRATIONS = ["Google Drive", "Gmail", "Google Calendar"];

export function Composer({
  value,
  onChange,
  onSend,
  streaming,
  model,
  onModel,
  turns,
  steps,
  tokens,
  tokensPerSecond,
  cacheHit,
  contextUsed,
}: Props) {
  const [modelOpen, setModelOpen] = useState(false);
  const [integrationsOpen, setIntegrationsOpen] = useState(false);

  return (
    <div className="px-3 pb-2 sm:px-5">
      <div className="mx-auto w-full max-w-[780px]">
        <div className="flex h-10 items-center gap-0.5 rounded-2xl border border-neutral-200 bg-neutral-100/80 px-1.5 shadow-[0_4px_18px_rgba(16,16,20,0.07)] sm:h-11">
          <button
            type="button"
            aria-label="Add"
            className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-neutral-500 transition-colors hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/15"
          >
            <Plus size={iconSize.md} strokeWidth={iconStroke} aria-hidden="true" />
          </button>

          <div className="relative hidden sm:block">
            <button
              type="button"
              aria-haspopup="menu"
              aria-expanded={integrationsOpen}
              onClick={() => setIntegrationsOpen((open) => !open)}
              className="flex h-8 items-center gap-1 rounded-full px-1.5 text-neutral-500 transition-colors hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/15"
              aria-label="Integrations"
            >
              <Plug size={iconSize.md} strokeWidth={iconStroke} aria-hidden="true" />
            </button>
            {integrationsOpen ? (
              <div className="absolute bottom-9 left-0 z-40 w-44 rounded-xl border border-neutral-200 bg-white p-1.5 shadow-xl">
                {INTEGRATIONS.map((item) => (
                  <button
                    key={item}
                    type="button"
                    className="flex w-full items-center rounded-md px-2 py-1.5 text-left text-[12px] text-neutral-700 hover:bg-neutral-100"
                  >
                    {item}
                  </button>
                ))}
              </div>
            ) : null}
          </div>

          <input
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                onSend();
              }
            }}
            placeholder="Message or run a task, / commands, @ files or sessions"
            className="min-w-0 flex-1 bg-transparent px-1 text-[13.5px] text-neutral-800 placeholder:text-neutral-400 focus:outline-none"
          />

          <div className="relative hidden sm:block">
            <button
              type="button"
              aria-haspopup="menu"
              aria-expanded={modelOpen}
              onClick={() => setModelOpen((open) => !open)}
              className="flex h-8 max-w-[104px] items-center gap-1 rounded-full px-1.5 text-[11.5px] text-neutral-600 transition-colors hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/15 sm:max-w-[160px] sm:text-[12px]"
            >
              <span className="truncate">{model}</span>
              <ChevronDown size={iconSize.xs} strokeWidth={iconStroke} aria-hidden="true" />
            </button>
            {modelOpen ? (
              <div className="absolute bottom-9 right-0 z-40 w-44 rounded-xl border border-neutral-200 bg-white p-1.5 shadow-xl">
                {MODELS.map((option) => (
                  <button
                    key={option}
                    type="button"
                    onClick={() => {
                      onModel(option);
                      setModelOpen(false);
                    }}
                    className={`flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-[12px] transition-colors hover:bg-neutral-100 focus-visible:bg-neutral-100 focus-visible:outline-none ${
                      option === model ? "font-medium text-neutral-900" : "text-neutral-700"
                    }`}
                  >
                    {option}
                    {option === model ? (
                      <Check
                        size={iconSize.sm}
                        strokeWidth={iconStroke}
                        aria-hidden="true"
                        className="text-blue-600"
                      />
                    ) : null}
                  </button>
                ))}
              </div>
            ) : null}
          </div>

          <button
            type="button"
            aria-label="Voice input"
            className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-neutral-500 transition-colors hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/15"
          >
            <Mic size={iconSize.md} strokeWidth={iconStroke} aria-hidden="true" />
          </button>

          <button
            type="button"
            aria-label="Send"
            onClick={onSend}
            disabled={streaming || value.trim() === ""}
            className="ml-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-blue-600 text-white transition-colors hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600/30 focus-visible:ring-offset-1 disabled:bg-neutral-300"
          >
            <ArrowUp size={iconSize.md} strokeWidth={iconStroke} aria-hidden="true" />
          </button>
        </div>

        <p
          data-testid="telemetry"
          className="mt-1 hidden flex-wrap items-center justify-center gap-x-1 gap-y-0 text-[10.5px] leading-4 text-neutral-400 sm:flex sm:justify-end"
        >
          <span>
            {turns} turns {steps} steps
          </span>
          <span>•</span>
          <span>{tokensPerSecond} tok/s</span>
          <span className="mx-1 text-neutral-300">|</span>
          <span>{tokens.toLocaleString()} tok</span>
          <span>•</span>
          <span>Cache hit {cacheHit}%</span>
          <span className="mx-1 hidden text-neutral-300 sm:inline">|</span>
          <span className="hidden sm:inline">{contextUsed}%</span>
        </p>
      </div>
    </div>
  );
}
