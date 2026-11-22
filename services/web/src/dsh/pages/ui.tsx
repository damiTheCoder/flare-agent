/** Shared page chrome: dense DSH tables. */

import type { ReactNode } from "react";

export function Page({ title, meta, children }: { title: string; meta?: string; children: ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-[1040px]">
      <div className="flex items-baseline justify-between gap-3">
        <h1 className="text-[15px] font-semibold tracking-tight text-neutral-900">{title}</h1>
        {meta !== undefined ? <span className="text-[11px] text-neutral-400">{meta}</span> : null}
      </div>
      <div className="mt-3">{children}</div>
    </div>
  );
}

export function Table({ head, children }: { head: ReactNode; children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-neutral-200">
      <table className="w-full border-collapse text-[12px]">
        <thead className="bg-neutral-50 text-[10px] uppercase tracking-[0.06em] text-neutral-500">
          {head}
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function Row({ children, muted = false }: { children: ReactNode; muted?: boolean }) {
  return (
    <tr className={`border-t border-neutral-100 hover:bg-neutral-50/70 ${muted ? "text-neutral-500" : ""}`}>
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
      className={`px-3 py-[6px] ${align === "right" ? "text-right tabular-nums" : "text-left"} ${
        strong ? "font-semibold text-neutral-900" : ""
      } ${className}`}
    >
      {children}
    </td>
  );
}

export function StatusPill({ status }: { status: string }) {
  const tone =
    status === "PAID"
      ? "bg-emerald-50 text-emerald-700"
      : status === "PENDING"
        ? "bg-amber-50 text-amber-700"
        : status === "DRAFT"
          ? "bg-neutral-100 text-neutral-600"
          : "bg-blue-50 text-blue-700";
  return (
    <span className={`rounded-full px-1.5 py-[1px] text-[9.5px] font-semibold ${tone}`}>{status}</span>
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
  if (loading) return <p className="py-6 text-[12px] text-neutral-400">Loading…</p>;
  if (error !== null)
    return <p className="py-6 text-[12px] text-rose-600">Could not load data: {error}</p>;
  if (empty === true) return <p className="py-6 text-[12px] text-neutral-400">Nothing here yet.</p>;
  return <>{children}</>;
}
