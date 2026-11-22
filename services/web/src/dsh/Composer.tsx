/** DSH composer: a filled grey card — message on top, controls underneath. */

import { useLayoutEffect, useRef, useState } from "react";
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
const MAX_INPUT_HEIGHT = 200;

const control =
  "grid h-9 w-9 shrink-0 place-items-center rounded-full text-neutral-500 transition-colors hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/15";

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
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  // Grow with the content, then scroll once it reaches the cap.
  useLayoutEffect(() => {
    const element = inputRef.current;
    if (element === null) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, MAX_INPUT_HEIGHT)}px`;
  }, [value]);

  return (
    <div className="px-3 pb-2 sm:px-5">
      <div className="mx-auto w-full max-w-[780px]">
        <div className="rounded-2xl bg-neutral-100 px-2.5 pb-2.5 pt-3 transition-shadow focus-within:ring-1 focus-within:ring-neutral-900/10">
          <textarea
            ref={inputRef}
            rows={1}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                onSend();
              }
            }}
            placeholder="Message or run a task, / commands, @ files or sessions"
            aria-label="Message"
            className="block max-h-[200px] min-h-[28px] w-full resize-none overflow-y-auto bg-transparent px-2.5 text-[14.5px] leading-[28px] text-neutral-800 placeholder:text-neutral-400 focus:outline-none"
          />

          <div className="mt-1.5 flex items-center gap-0.5">
            <button type="button" aria-label="Add" className={control}>
              <Plus size={iconSize.lg} strokeWidth={iconStroke} aria-hidden="true" />
            </button>

            <div className="relative hidden sm:block">
              <button
                type="button"
                aria-haspopup="menu"
                aria-expanded={integrationsOpen}
                aria-label="Integrations"
                onClick={() => setIntegrationsOpen((open) => !open)}
                className="flex h-9 items-center gap-1 rounded-full px-2 text-neutral-500 transition-colors hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/15"
              >
                <Plug size={iconSize.lg} strokeWidth={iconStroke} aria-hidden="true" />
              </button>
              {integrationsOpen ? (
                <div className="absolute bottom-full left-0 z-40 mb-1 w-44 rounded-xl border border-neutral-200 bg-white p-1.5 shadow-xl">
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

            <div className="flex-1" />

            <div className="relative hidden sm:block">
              <button
                type="button"
                aria-haspopup="menu"
                aria-expanded={modelOpen}
                onClick={() => setModelOpen((open) => !open)}
                className="flex h-9 max-w-[112px] items-center gap-1 rounded-full px-2 text-[12.5px] text-neutral-600 transition-colors hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/15 sm:max-w-[176px] sm:text-[13px]"
              >
                <span className="truncate">{model}</span>
                <ChevronDown size={iconSize.sm} strokeWidth={iconStroke} aria-hidden="true" />
              </button>
              {modelOpen ? (
                <div className="absolute bottom-full right-0 z-40 mb-1 w-44 rounded-xl border border-neutral-200 bg-white p-1.5 shadow-xl">
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

            <button type="button" aria-label="Voice input" className={control}>
              <Mic size={iconSize.lg} strokeWidth={iconStroke} aria-hidden="true" />
            </button>

            <button
              type="button"
              aria-label="Send"
              onClick={onSend}
              disabled={streaming || value.trim() === ""}
              className="ml-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-full bg-blue-600 text-white transition-colors hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600/30 focus-visible:ring-offset-1 disabled:bg-neutral-300"
            >
              <ArrowUp size={iconSize.lg} strokeWidth={iconStroke} aria-hidden="true" />
            </button>
          </div>
        </div>

        <p
          data-testid="telemetry"
          className="mt-1.5 flex flex-wrap items-center justify-center gap-x-1.5 gap-y-0 text-[11px] leading-4 text-neutral-400 sm:justify-end"
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
          <span className="mx-1 text-neutral-300">|</span>
          <span>{contextUsed}%</span>
        </p>
      </div>
    </div>
  );
}
