/** DSH composer: a filled grey card — message on top, controls underneath. */

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  ArrowUp,
  Check,
  ChevronDown,
  FileText,
  Mic,
  Plug,
  Plus,
  Volume2,
  VolumeX,
} from "lucide-react";
import { iconSize, iconStroke } from "./icons";

type Props = {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  streaming: boolean;
  model: string;
  onModel: (model: string) => void;
  speechEnabled: boolean;
  onToggleSpeech: () => void;
  turns: number;
  steps: number;
  tokens: number;
  tokensPerSecond: number;
  cacheHit: number;
  contextUsed: number;
};

type Command = { name: string; description: string };

type Picker =
  | { kind: "command"; query: string; start: number; end: number }
  | { kind: "file"; query: string; start: number; end: number }
  | null;

type SpeechResult = { isFinal: boolean; [index: number]: { transcript: string } };
type SpeechEvent = {
  resultIndex: number;
  results: { length: number; [index: number]: SpeechResult };
};
type Recognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  onresult: ((event: SpeechEvent) => void) | null;
};
type RecognitionCtor = new () => Recognition;

const MODELS = ["deepseek-chat", "deepseek-reasoner"];
const INTEGRATIONS = ["Google Drive", "Gmail", "Google Calendar"];
const MAX_INPUT_HEIGHT = 200;

const control =
  "grid h-9 w-9 shrink-0 place-items-center rounded-full text-neutral-500 transition-colors hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/15";

function recognitionCtor(): RecognitionCtor | null {
  const scope = window as unknown as {
    SpeechRecognition?: RecognitionCtor;
    webkitSpeechRecognition?: RecognitionCtor;
  };
  return scope.SpeechRecognition ?? scope.webkitSpeechRecognition ?? null;
}

export function Composer({
  value,
  onChange,
  onSend,
  streaming,
  model,
  onModel,
  speechEnabled,
  onToggleSpeech,
  turns,
  steps,
  tokens,
  tokensPerSecond,
  cacheHit,
  contextUsed,
}: Props) {
  const [modelOpen, setModelOpen] = useState(false);
  const [integrationsOpen, setIntegrationsOpen] = useState(false);
  const [picker, setPicker] = useState<Picker>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const [commands, setCommands] = useState<Command[]>([]);
  const [files, setFiles] = useState<string[]>([]);
  const [listening, setListening] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [loadingCommands, setLoadingCommands] = useState(false);
  const [loadingFiles, setLoadingFiles] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const recognitionRef = useRef<Recognition | null>(null);
  const voiceBaseRef = useRef("");
  const commandsLoaded = useRef(false);
  const filesLoaded = useRef(false);

  // Grow with the content, then scroll once it reaches the cap.
  useLayoutEffect(() => {
    const element = inputRef.current;
    if (element === null) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, MAX_INPUT_HEIGHT)}px`;
  }, [value]);

  useEffect(
    () => () => {
      recognitionRef.current?.abort();
    },
    [],
  );

  const loadCommands = async () => {
    if (commandsLoaded.current) return;
    commandsLoaded.current = true;
    setLoadingCommands(true);
    try {
      const response = await fetch("/v1/commands");
      if (response.ok) setCommands((await response.json()) as Command[]);
    } catch {
      commandsLoaded.current = false;
    } finally {
      setLoadingCommands(false);
    }
  };

  const loadFiles = async () => {
    if (filesLoaded.current) return;
    filesLoaded.current = true;
    setLoadingFiles(true);
    try {
      const response = await fetch("/v1/workspaces/files");
      if (response.ok) {
        const payload = (await response.json()) as { files: string[] };
        setFiles(payload.files);
      }
    } catch {
      filesLoaded.current = false;
    } finally {
      setLoadingFiles(false);
    }
  };

  // Warm both pickers so the first "/" and "@" are instant.
  useEffect(() => {
    void loadCommands();
    void loadFiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A cleared draft can no longer have an open picker (send, new chat, reset).
  useEffect(() => {
    if (value === "") setPicker(null);
  }, [value]);

  const updatePicker = (text: string, caret: number) => {
    const before = text.slice(0, caret);
    const command = /(?:^|\n)\/([a-zA-Z0-9_-]*)$/.exec(before);
    if (command) {
      void loadCommands();
      setPicker({
        kind: "command",
        query: command[1],
        start: caret - command[1].length - 1,
        end: caret,
      });
      setActiveIndex(0);
      return;
    }
    const file = /(^|\s)@([^\s@]*)$/.exec(before);
    if (file) {
      void loadFiles();
      setPicker({
        kind: "file",
        query: file[2],
        start: caret - file[2].length - 1,
        end: caret,
      });
      setActiveIndex(0);
      return;
    }
    setPicker(null);
  };

  const insert = (token: string) => {
    if (picker === null) return;
    const next = value.slice(0, picker.start) + token + value.slice(picker.end);
    onChange(next);
    setPicker(null);
    const caret = picker.start + token.length;
    requestAnimationFrame(() => {
      const input = inputRef.current;
      if (input === null) return;
      input.focus();
      input.setSelectionRange(caret, caret);
    });
  };

  const commandOptions =
    picker?.kind === "command"
      ? commands.filter((item) =>
          item.name.toLowerCase().startsWith(picker.query.toLowerCase()),
        )
      : [];
  const fileOptions =
    picker?.kind === "file"
      ? files
          .filter((path) => path.toLowerCase().includes(picker.query.toLowerCase()))
          .slice(0, 60)
      : [];
  const optionCount = picker?.kind === "command" ? commandOptions.length : fileOptions.length;
  const activeOption = Math.min(activeIndex, Math.max(optionCount - 1, 0));
  const pickerLoading =
    picker?.kind === "command" ? loadingCommands : picker?.kind === "file" ? loadingFiles : false;

  const chooseActive = () => {
    if (picker === null || optionCount === 0) return;
    if (picker.kind === "command") insert(`/${commandOptions[activeOption].name} `);
    else insert(`@${fileOptions[activeOption]} `);
  };

  const toggleVoice = () => {
    const Ctor = recognitionCtor();
    if (Ctor === null) {
      setVoiceError("Voice input is not supported in this browser.");
      return;
    }
    if (listening) {
      recognitionRef.current?.stop();
      return;
    }
    setVoiceError(null);
    voiceBaseRef.current = value.trimEnd();
    const recognition = new Ctor();
    recognition.lang = navigator.language || "en-US";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onstart = () => setListening(true);
    recognition.onend = () => setListening(false);
    recognition.onerror = (event) => {
      setListening(false);
      if (event.error !== "aborted") {
        setVoiceError("Voice input failed. Check the microphone permission.");
      }
    };
    recognition.onresult = (event: SpeechEvent) => {
      let transcript = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (result.isFinal) transcript += result[0].transcript;
      }
      const text = transcript.trim();
      if (text === "") return;
      setPicker(null);
      const base = voiceBaseRef.current;
      onChange(base === "" ? text : `${base} ${text}`);
    };
    recognitionRef.current = recognition;
    try {
      recognition.start();
      setListening(true);
    } catch {
      setVoiceError("Voice input could not start.");
    }
  };

  return (
    <div className="px-3 pb-2 sm:px-5">
      <div className="mx-auto w-full max-w-[780px]">
        <div className="relative rounded-2xl bg-neutral-100 px-2.5 pb-2.5 pt-3 transition-shadow focus-within:ring-1 focus-within:ring-neutral-900/10">
          {picker !== null ? (
            <div
              role="listbox"
              aria-label={picker.kind === "command" ? "Slash commands" : "Workspace files"}
              className="absolute bottom-full left-0 right-0 z-40 mb-2 max-h-[260px] overflow-y-auto rounded-xl border border-neutral-200 bg-white p-1 shadow-[0_16px_40px_rgba(16,16,20,0.16)]"
            >
              <p className="px-2 pb-1 pt-1.5 text-[10px] font-medium uppercase tracking-[0.06em] text-neutral-400">
                {picker.kind === "command" ? "Commands" : "Files"}
              </p>
              {optionCount === 0 ? (
                <p className="px-2 py-2 text-[12px] text-neutral-400">
                  {pickerLoading
                    ? "Loading…"
                    : picker.kind === "command"
                      ? "No matching commands"
                      : "No matching files"}
                </p>
              ) : picker.kind === "command" ? (
                commandOptions.map((item, index) => (
                  <button
                    key={item.name}
                    type="button"
                    role="option"
                    aria-selected={index === activeOption}
                    onMouseEnter={() => setActiveIndex(index)}
                    onClick={() => insert(`/${item.name} `)}
                    className={`flex w-full items-baseline gap-2 rounded-md px-2 py-1.5 text-left transition-colors ${
                      index === activeOption ? "bg-neutral-100" : ""
                    }`}
                  >
                    <span className="font-mono text-[12.5px] text-neutral-900">
                      /{item.name}
                    </span>
                    <span className="truncate text-[11.5px] text-neutral-400">
                      {item.description}
                    </span>
                  </button>
                ))
              ) : (
                fileOptions.map((path, index) => (
                  <button
                    key={path}
                    type="button"
                    role="option"
                    aria-selected={index === activeOption}
                    onMouseEnter={() => setActiveIndex(index)}
                    onClick={() => insert(`@${path} `)}
                    className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors ${
                      index === activeOption ? "bg-neutral-100" : ""
                    }`}
                  >
                    <FileText
                      size={iconSize.sm}
                      strokeWidth={iconStroke}
                      aria-hidden="true"
                      className="shrink-0 text-neutral-400"
                    />
                    <span className="truncate text-[12.5px] text-neutral-700">{path}</span>
                  </button>
                ))
              )}
            </div>
          ) : null}

          <textarea
            ref={inputRef}
            rows={1}
            value={value}
            onChange={(event) => {
              const next = event.target.value;
              onChange(next);
              updatePicker(next, event.target.selectionStart ?? next.length);
            }}
            onKeyDown={(event) => {
              if (picker !== null) {
                if (event.key === "Escape") {
                  event.preventDefault();
                  setPicker(null);
                  return;
                }
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  if (optionCount > 0) chooseActive();
                  else setPicker(null);
                  return;
                }
                if (event.key === "ArrowDown" && optionCount > 0) {
                  event.preventDefault();
                  setActiveIndex((activeOption + 1) % optionCount);
                  return;
                }
                if (event.key === "ArrowUp" && optionCount > 0) {
                  event.preventDefault();
                  setActiveIndex((activeOption - 1 + optionCount) % optionCount);
                  return;
                }
              }
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                setPicker(null);
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

            <button
              type="button"
              aria-pressed={speechEnabled}
              aria-label={speechEnabled ? "Turn off read aloud" : "Read replies aloud"}
              title={speechEnabled ? "Read aloud: on" : "Read aloud: off"}
              onClick={onToggleSpeech}
              className={`grid h-9 w-9 shrink-0 place-items-center rounded-full transition-colors hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/15 ${
                speechEnabled ? "bg-white text-neutral-900" : "text-neutral-500"
              }`}
            >
              {speechEnabled ? (
                <Volume2 size={iconSize.lg} strokeWidth={iconStroke} aria-hidden="true" />
              ) : (
                <VolumeX size={iconSize.lg} strokeWidth={iconStroke} aria-hidden="true" />
              )}
            </button>

            <button
              type="button"
              aria-label={listening ? "Stop voice input" : "Voice input"}
              aria-pressed={listening}
              title={listening ? "Listening…" : "Voice input"}
              onClick={toggleVoice}
              className={`grid h-9 w-9 shrink-0 place-items-center rounded-full transition-colors hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/15 ${
                listening ? "bg-white text-rose-600" : "text-neutral-500"
              }`}
            >
              <Mic
                size={iconSize.lg}
                strokeWidth={iconStroke}
                aria-hidden="true"
                className={listening ? "animate-pulse" : undefined}
              />
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

          {voiceError !== null ? (
            <p role="alert" className="mt-1.5 px-1 text-[11px] text-rose-600">
              {voiceError}
            </p>
          ) : null}
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
