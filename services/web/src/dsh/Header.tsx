/** DSH top bar: sidebar toggle + brand on the left, session title centered,
 * "..." session menu on the right. */

import { useEffect, useRef, useState } from "react";

type Props = {
  title: string;
  onToggleSidebar: () => void;
  onCopyMarkdown: () => void;
  onDownloadLog: () => void;
};

const menuItem =
  "flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-[12.5px] text-neutral-700 hover:bg-neutral-100";

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
    <header className="relative flex h-11 shrink-0 items-center gap-2 border-b border-neutral-200 bg-white px-3">
      <button
        type="button"
        aria-label="Toggle sidebar"
        onClick={onToggleSidebar}
        className="grid h-7 w-7 place-items-center rounded-md text-neutral-500 hover:bg-neutral-100"
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <rect x="3" y="4" width="18" height="16" rx="2.5" />
          <path d="M9 4v16" />
        </svg>
      </button>

      <span className="grid h-[18px] w-[18px] place-items-center rounded-[5px] bg-blue-600 text-[10px] font-bold text-white">
        M
      </span>
      <span className="text-[13px] font-semibold tracking-tight text-neutral-900">MicroBalance</span>

      <span className="pointer-events-none absolute left-1/2 max-w-[46%] -translate-x-1/2 truncate text-[12px] text-neutral-500">
        {title}
      </span>

      <div className="relative ml-auto" ref={menuRef}>
        <button
          type="button"
          aria-label="Session menu"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((open) => !open)}
          className="grid h-7 w-7 place-items-center rounded-md text-neutral-500 hover:bg-neutral-100"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <circle cx="5" cy="12" r="1.5" />
            <circle cx="12" cy="12" r="1.5" />
            <circle cx="19" cy="12" r="1.5" />
          </svg>
        </button>

        {menuOpen ? (
          <div
            role="menu"
            data-testid="session-menu"
            className="absolute right-0 top-9 z-50 w-56 rounded-xl border border-neutral-200 bg-white p-1.5 shadow-[0_16px_48px_rgba(16,16,20,0.18)]"
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
              Copy Session as Markdown
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
              Download session log
            </button>
            <button type="button" role="menuitem" className={menuItem}>
              Open in
              <span className="text-neutral-400">›</span>
            </button>
            <div className="my-1 h-px bg-neutral-100" />
            <button type="button" role="menuitem" className={menuItem}>
              Feedback
            </button>
          </div>
        ) : null}
      </div>
    </header>
  );
}
