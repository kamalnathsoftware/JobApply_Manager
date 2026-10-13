import { Link } from "react-router-dom";
import { useStats } from "../api/hooks";
import { Badge, Card, Empty, PageHeader, SITE_COLOR, fmt } from "../components/ui";

export default function Dashboard() {
  const { data: s, isLoading, error } = useStats();
  if (isLoading) return <p>Loading…</p>;
  if (error || !s) return <p className="text-red-600">Could not load stats.</p>;
  const sites = Object.keys(s.applied_by_site);
  const max = Math.max(1, ...s.applied_per_day.map((d) => sites.reduce((n, k) => n + Number(d[k] ?? 0), 0)));
  const stat = (label: string, n: number, to?: string) => (
    <Card><div className="text-3xl font-bold">{n}</div><div className="text-sm text-slate-500">{to ? <Link className="underline" to={to}>{label}</Link> : label}</div></Card>
  );
  return (
    <div className="space-y-6">
      <PageHeader title="Dashboard" />
      <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
        {stat("Applied", s.by_status.applied ?? 0, "/applications?status=applied")}
        {stat("Awaiting approval", s.attention.awaiting_approval, "/review")}
        {stat("Need you", s.attention.needs_human, "/review")}
        {stat("Matched (dry run)", s.by_status.found ?? 0, "/applications?status=found")}
        {stat("Accounts to fix", s.attention.accounts_need_login, "/accounts")}
      </div>
      <Card>
        <h3 className="mb-3 font-semibold">Applications per day, by site</h3>
        {sites.length === 0 ? <Empty>No applications yet. Create a schedule in <b>auto</b> or approve items in the review queue.</Empty> : (
          <>
            <div className="flex h-40 items-end gap-1">
              {s.applied_per_day.map((d) => (
                <div key={d.date} className="flex h-full flex-1 flex-col-reverse" title={`${d.date}: ${sites.map((k) => `${k} ${d[k] ?? 0}`).join(", ")}`}>
                  {sites.map((k) => Number(d[k] ?? 0) > 0 && <div key={k} style={{ height: `${(Number(d[k]) / max) * 100}%`, background: SITE_COLOR[k] }} className="min-h-[2px]" />)}
                </div>
              ))}
            </div>
            <div className="mt-1 flex justify-between text-xs text-slate-500"><span>{s.applied_per_day[0]?.date}</span><span>{s.applied_per_day.at(-1)?.date}</span></div>
            <div className="mt-2 flex gap-4 text-xs">{sites.map((k) => <span key={k}><i className="mr-1 inline-block h-2 w-2" style={{ background: SITE_COLOR[k] }} />{k} ({s.applied_by_site[k]})</span>)}</div>
          </>
        )}
      </Card>
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <h3 className="mb-3 font-semibold">Today per account</h3>
          {s.accounts.length === 0 ? <Empty>No accounts yet.</Empty> : s.accounts.map((a) => (
            <div key={a.id} className="mb-3 text-sm">
              <div className="flex justify-between"><span>{a.label} <span className="text-slate-400">({a.site})</span></span><span>{a.applied_today}/{a.cap} <Badge>{a.status}</Badge></span></div>
              <div className="mt-1 h-2 rounded bg-slate-100"><div className="h-2 rounded bg-slate-800" style={{ width: `${Math.min(100, (a.applied_today / a.cap) * 100)}%` }} /></div>
            </div>
          ))}
        </Card>
        <Card>
          <h3 className="mb-3 font-semibold">Recent runs</h3>
          {s.recent_runs.length === 0 ? <Empty>No runs yet.</Empty> : s.recent_runs.map((r) => (
            <div key={r.id} className="mb-2 flex items-center justify-between text-sm">
              <span>#{r.id} {r.schedule} <span className="text-slate-400">{fmt(r.started_at)}</span></span>
              <span><Badge>{r.status}</Badge> {r.summary && <span className="text-xs text-slate-500">applied {r.summary.applied ?? 0} · queued {r.summary.queued ?? 0}</span>}</span>
            </div>
          ))}
        </Card>
      </div>
    </div>
  );
}
