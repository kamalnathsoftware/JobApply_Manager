import type { ButtonHTMLAttributes, ReactNode } from "react";

export const inputCls = "w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm focus:border-slate-500 focus:outline-none";

export function Button({ variant = "primary", small, className = "", ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger"; small?: boolean }) {
  const v = { primary: "bg-slate-900 text-white hover:bg-slate-700", secondary: "border border-slate-300 bg-white hover:bg-slate-100", danger: "bg-red-600 text-white hover:bg-red-500" }[variant];
  return <button {...p} className={`rounded ${small ? "px-2 py-1 text-xs" : "px-3 py-2 text-sm"} font-medium disabled:opacity-50 ${v} ${className}`} />;
}

export const Card = ({ children, className = "" }: { children: ReactNode; className?: string }) => (
  <div className={`rounded-lg border border-slate-200 bg-white p-4 shadow-sm ${className}`}>{children}</div>
);

export function PageHeader({ title, action, subtitle }: { title: string; action?: ReactNode; subtitle?: string }) {
  return (
    <div className="mb-5 flex items-start justify-between gap-4">
      <div><h2 className="text-2xl font-bold">{title}</h2>{subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}</div>
      {action}
    </div>
  );
}

const COLORS: Record<string, string> = {
  applied: "bg-green-100 text-green-800", active: "bg-green-100 text-green-800", parsed: "bg-green-100 text-green-800", completed: "bg-green-100 text-green-800",
  queued: "bg-amber-100 text-amber-800", pending: "bg-amber-100 text-amber-800", running: "bg-blue-100 text-blue-800", login_in_progress: "bg-blue-100 text-blue-800",
  found: "bg-sky-100 text-sky-800", skipped: "bg-slate-100 text-slate-600", new: "bg-slate-100 text-slate-600", disabled: "bg-slate-200 text-slate-600",
  failed: "bg-red-100 text-red-800", parse_failed: "bg-red-100 text-red-800", needs_human: "bg-orange-100 text-orange-800", needs_login: "bg-orange-100 text-orange-800",
};
export const Badge = ({ children }: { children: string }) => (
  <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${COLORS[children] ?? "bg-slate-100 text-slate-700"}`}>{children.replace(/_/g, " ")}</span>
);

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-black/40 p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`mt-8 w-full ${wide ? "max-w-3xl" : "max-w-xl"} rounded-lg bg-white p-5 shadow-xl`}>
        <div className="mb-4 flex items-center justify-between"><h3 className="text-lg font-semibold">{title}</h3><button onClick={onClose} className="text-slate-500 hover:text-slate-900">✕</button></div>
        {children}
      </div>
    </div>
  );
}

export const Field = ({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) => (
  <label className="block text-sm"><span className="mb-1 block font-medium text-slate-700">{label}</span>{children}{hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}</label>
);

export const ErrorText = ({ error }: { error: unknown }) => error ? <p className="text-sm text-red-600">{error instanceof Error ? error.message : String(error)}</p> : null;
export const Empty = ({ children }: { children: ReactNode }) => <p className="rounded border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">{children}</p>;

export const SITE_COLOR: Record<string, string> = { naukri: "#2563eb", linkedin: "#0891b2", indeed: "#7c3aed", company: "#64748b" };
export const csv = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
export const fmt = (d: string | null) => (d ? new Date(d + (d.endsWith("Z") ? "" : "Z")).toLocaleString() : "—");
