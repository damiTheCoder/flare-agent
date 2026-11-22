/** DSH top bar: sidebar toggle + brand on the left, session title centered,
 * "..." session menu on the right. */

import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  ChevronRight,
  Copy,
  Download,
  Ellipsis,
  ExternalLink,
  MessageCircle,
  PanelLeft,
  type LucideIcon,
} from "lucide-react";
import { iconSize, iconStroke } from "./icons";

type Props = {
  title: string;
  onToggleSidebar: () => void;
  onCopyMarkdown: () => void;
  onDownloadLog: () => void;
};

const menuItem =
  "flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-[12.5px] text-neutral-700 transition-colors hover:bg-neutral-100 focus-visible:bg-neutral-100 focus-visible:outline-none";

function MenuLabel({ icon: Icon, children }: { icon: LucideIcon; children: ReactNode }) {
  return (
    <span className="flex items-center gap-2">
      <Icon
        size={iconSize.md}
        strokeWidth={iconStroke}
        aria-hidden="true"
        className="text-neutral-400"
      />
      {children}
    </span>
  );
}

export function Header({ title, onToggleSidebar, onCopyMarkdown, onDownloadLog }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: MouseEvent) => {
      if (menuRef.current !== null && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", escape);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", escape);
    };
  }, [menuOpen]);

  return (
    <header className="relative flex h-11 shrink-0 items-center gap-1.5 bg-white px-2 sm:gap-2 sm:px-3">
      <button
        type="button"
        aria-label="Toggle sidebar"
        onClick={onToggleSidebar}
        className="grid h-8 w-8 place-items-center rounded-md text-neutral-500 transition-colors hover:bg-neutral-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/15"
      >
        <PanelLeft size={iconSize.lg} strokeWidth={iconStroke} aria-hidden="true" />
      </button>

      <img
        src="/logo.png"
        alt=""
        aria-hidden="true"
        className="h-[18px] w-7 rounded-[5px] object-cover lg:hidden"
      />
      <span className="hidden text-[13px] font-semibold tracking-tight text-neutral-900 sm:inline lg:hidden">
        MicroBalance
      </span>

      <span className="pointer-events-none absolute left-1/2 max-w-[42%] -translate-x-1/2 truncate text-[12px] text-neutral-500 sm:max-w-[46%] sm:text-[12.5px]">
        {title}
      </span>

      <div className="relative ml-auto" ref={menuRef}>
        <button
          type="button"
          aria-label="Session menu"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((open) => !open)}
          className="grid h-8 w-8 place-items-center rounded-md text-neutral-500 transition-colors hover:bg-neutral-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/15"
        >
          <Ellipsis size={iconSize.lg} strokeWidth={iconStroke} aria-hidden="true" />
        </button>

        {menuOpen ? (
          <div
            role="menu"
            data-testid="session-menu"
            className="absolute right-0 top-10 z-50 w-56 rounded-xl border border-neutral-200 bg-white p-1.5 shadow-[0_12px_32px_rgba(16,16,20,0.14)]"
          >
            <button
              type="button"
              role="menuitem"
              className={menuItem}
              onClick={() => {
                onCopyMarkdown();
                setMenuOpen(false);
              }}
            >
              <MenuLabel icon={Copy}>Copy session as Markdown</MenuLabel>
            </button>
            <button
              type="button"
              role="menuitem"
              className={menuItem}
              onClick={() => {
                onDownloadLog();
                setMenuOpen(false);
              }}
            >
              <MenuLabel icon={Download}>Download session log</MenuLabel>
            </button>
            <button type="button" role="menuitem" className={menuItem}>
              <MenuLabel icon={ExternalLink}>Open in</MenuLabel>
              <ChevronRight
                size={iconSize.sm}
                strokeWidth={iconStroke}
                aria-hidden="true"
                className="text-neutral-400"
              />
            </button>
            <div className="my-1 h-px bg-neutral-100" />
            <button type="button" role="menuitem" className={menuItem}>
              <MenuLabel icon={MessageCircle}>Feedback</MenuLabel>
            </button>
          </div>
        ) : null}
      </div>
    </header>
  );
}
