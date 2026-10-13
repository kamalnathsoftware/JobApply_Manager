import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useAccounts, useApplications, useSend } from "../api/hooks";
import AppDetail from "../components/AppDetail";
import { Badge, Button, Empty, PageHeader, fmt, inputCls } from "../components/ui";

const STATUSES = ["found", "queued", "applied", "failed", "needs_human", "skipped"];
const PAGE = 25;

export default function Applications() {
  const [sp, setSp] = useSearchParams();
  const [offset, setOffset] = useState(0);
  const [detail, setDetail] = useState<number | null>(null);
  const { data: accounts = [] } = useAccounts();
  const get = (k: string) => sp.get(k) ?? "";
  const set = (k: string, v: string) => { const n = new URLSearchParams(sp); v ? n.set(k, v) : n.delete(k); setSp(n); setOffset(0); };
  const qs = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
  ["status", "site", "account_id", "q", "min_score"].forEach((k) => get(k) && qs.set(k, get(k)));
  if (get("from")) qs.set("date_from", get("from"));
  if (get("to")) qs.set("date_to", get("to") + "T23:59:59");
  const { data, isLoading } = useApplications(qs.toString());
  const retry = useSend<unknown, number>("POST", (id) => `/applications/${id}/retry`, ["applications"]);
  return (
    <div className="space-y-4">
      <PageHeader title="Applications" subtitle="Every job found, scored and (maybe) applied to." />
      <div className="grid gap-2 md:grid-cols-4 lg:grid-cols-7">
        <input className={inputCls} placeholder="Search title / company" value={get("q")} onChange={(e) => set("q", e.target.value)} />
        <select className={inputCls} value={get("status")} onChange={(e) => set("status", e.target.value)}><option value="">All statuses</option>{STATUSES.map((s) => <option key={s}>{s}</option>)}</select>
        <select className={inputCls} value={get("site")} onChange={(e) => set("site", e.target.value)}><option value="">All sites</option>{["naukri", "linkedin", "indeed", "company"].map((s) => <option key={s}>{s}</option>)}</select>
        <select className={inputCls} value={get("account_id")} onChange={(e) => set("account_id", e.target.value)}><option value="">All accounts</option>{accounts.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}</select>
        <input type="number" min={0} max={100} className={inputCls} placeholder="Min score" value={get("min_score")} onChange={(e) => set("min_score", e.target.value)} />
        <input type="date" className={inputCls} value={get("from")} onChange={(e) => set("from", e.target.value)} title="From" />
        <input type="date" className={inputCls} value={get("to")} onChange={(e) => set("to", e.target.value)} title="To" />
      </div>
      {isLoading ? <p>Loading…</p> : !data || data.items.length === 0 ? <Empty>No applications match.</Empty> : (
        <div className="overflow-x-auto rounded-lg border bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr><th className="p-2">Job</th><th>Site / account</th><th>Score</th><th>Status</th><th>When</th><th /></tr></thead>
            <tbody>
              {data.items.map((a) => (
                <tr key={a.id} className="border-t hover:bg-slate-50">
                  <td className="p-2"><button className="text-left font-medium hover:underline" onClick={() => setDetail(a.id)}>{a.job.title}</button><div className="text-xs text-slate-500">{a.job.company}{a.job.location ? ` · ${a.job.location}` : ""}</div></td>
                  <td>{a.job.site}<div className="text-xs text-slate-500">{a.account_label}</div></td>
                  <td>{a.score ?? "—"}</td>
                  <td><Badge>{a.status}</Badge>{a.status_note && <div className="max-w-xs truncate text-xs text-slate-500" title={a.status_note}>{a.status_note}</div>}</td>
                  <td className="text-xs">{fmt(a.applied_at ?? a.created_at)}</td>
                  <td>{a.status === "failed" && <Button small variant="secondary" onClick={() => retry.mutate(a.id)}>Retry</Button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && data.total > PAGE && (
        <div className="flex items-center justify-between text-sm"><span>{offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total}</span>
          <span className="flex gap-2"><Button small variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Prev</Button><Button small variant="secondary" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>Next</Button></span></div>
      )}
      {detail !== null && <AppDetail id={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}
