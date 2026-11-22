/** Shared page chrome: dense DSH tables. */

import type { ReactNode } from "react";
import { Inbox, LoaderCircle } from "lucide-react";
import { iconSize, iconStroke } from "../icons";

export function Page({ title, meta, children }: { title: string; meta?: string; children: ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-[1040px]">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h1 className="text-[22px] font-semibold leading-tight tracking-[-0.01em] text-neutral-900">
          {title}
        </h1>
        {meta !== undefined ? (
          <span className="text-[11px] leading-none text-neutral-400">{meta}</span>
        ) : null}
      </div>
      <div className="mt-4">{children}</div>
    </div>
  );
}

export function Table({ head, children }: { head: ReactNode; children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-neutral-200 bg-white">
      <table className="w-full border-collapse text-[12.5px] leading-[1.45]">
        <thead className="bg-neutral-50 text-[10.5px] uppercase tracking-[0.05em] text-neutral-500">
          {head}
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function Row({ children, muted = false }: { children: ReactNode; muted?: boolean }) {
  return (
    <tr
      className={`border-t border-neutral-100 transition-colors duration-150 hover:bg-neutral-50/80 ${
        muted ? "text-neutral-500" : ""
      }`}
    >
      {children}
    </tr>
  );
}

export function Cell({
  children,
  align = "left",
  strong = false,
  className = "",
}: {
  children: ReactNode;
  align?: "left" | "right";
  strong?: boolean;
  className?: string;
}) {
  return (
    <td
      className={`px-3 py-[9px] align-middle ${
        align === "right" ? "text-right tabular-nums" : "text-left"
      } ${strong ? "font-semibold text-neutral-900" : ""} ${className}`}
    >
      {children}
    </td>
  );
}

const PILL_TONES: Record<string, string> = {
  PAID: "bg-emerald-50 text-emerald-700",
  POSTED: "bg-emerald-50 text-emerald-700",
  ACTIVE: "bg-emerald-50 text-emerald-700",
  RECONCILED: "bg-emerald-50 text-emerald-700",
  PENDING: "bg-amber-50 text-amber-700",
  UNRECONCILED: "bg-amber-50 text-amber-700",
  DRAFT: "bg-neutral-100 text-neutral-600",
  INACTIVE: "bg-neutral-100 text-neutral-500",
  RECEIVED: "bg-blue-50 text-blue-700",
};

export function StatusPill({ status }: { status: string }) {
  const tone = PILL_TONES[status] ?? "bg-blue-50 text-blue-700";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-[2px] text-[10.5px] font-semibold leading-none ${tone}`}
    >
      {status}
    </span>
  );
}

function Spinner() {
  return (
    <LoaderCircle
      size={iconSize.sm}
      strokeWidth={iconStroke}
      className="animate-spin"
      aria-hidden="true"
    />
  );
}

function InboxIcon() {
  return (
    <Inbox
      size={iconSize.xxxl}
      strokeWidth={iconStroke}
      className="text-neutral-300"
      aria-hidden="true"
    />
  );
}

export function PageState({
  loading,
  error,
  empty,
  children,
}: {
  loading: boolean;
  error: string | null;
  empty?: boolean;
  children: ReactNode;
}) {
  if (loading) {
    return (
      <div className="flex items-center gap-2 py-8 text-[12.5px] text-neutral-400" role="status">
        <Spinner />
        Loading…
      </div>
    );
  }
  if (error !== null) {
    return (
      <div
        role="alert"
        className="rounded-md border border-rose-200 bg-rose-50/60 px-3 py-2 text-[12.5px] text-rose-700"
      >
        Could not load data: {error}
      </div>
    );
  }
  if (empty === true) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-neutral-200 bg-neutral-50/40 px-4 py-10 text-center">
        <InboxIcon />
        <p className="text-[12.5px] font-medium text-neutral-600">Nothing here yet</p>
        <p className="max-w-[34ch] text-[11.5px] leading-relaxed text-neutral-400">
          Records will appear here as they are created.
        </p>
      </div>
    );
  }
  return <>{children}</>;
}
