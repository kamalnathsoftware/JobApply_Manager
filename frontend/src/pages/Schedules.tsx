import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiUrl } from "../api/client";
import { useAccounts, useProfiles, useRuns, useSchedules, useSend } from "../api/hooks";
import type { LogEntry, Run, Schedule } from "../api/types";
import WorkerBanner from "../components/WorkerBanner";
import { Badge, Button, Card, Empty, ErrorText, Field, Modal, PageHeader, fmt, inputCls } from "../components/ui";

const MODES = { dry_run: "Only find & score (never apply)", review: "Queue for my approval (Review Queue)", auto: "Apply automatically" } as const;

export default function Schedules() {
  const { data = [], isLoading } = useSchedules();
  const { data: accounts = [] } = useAccounts();
  const { data: runs = [] } = useRuns(undefined, 4000);
  const [editing, setEditing] = useState<Schedule | "new" | null>(null);
  const [watch, setWatch] = useState<number | null>(null);
  const run = useSend<Run, number>("POST", (id) => `/schedules/${id}/run`, ["runs"]);
  const cancel = useSend<Run, number>("POST", (id) => `/runs/${id}/cancel`, ["runs"]);
  const qc = useQueryClient();
  const runNow = async (id: number) => {
    try { // make sure a worker exists, otherwise the run would sit in "pending"
      const w = await api<{ alive: boolean }>("/system/worker");
      if (!w.alive) { await api("/system/worker/start", { method: "POST" }); qc.invalidateQueries({ queryKey: ["worker"] }); }
    } catch { /* the banner explains how to start it */ }
    run.mutate(id, { onSuccess: (r) => setWatch(r.id) });
  };
  const del = useSend<void, number>("DELETE", (id) => `/schedules/${id}`, ["schedules", "runs"]);
  const toggle = useSend<Schedule, Schedule>("PUT", (s) => `/schedules/${s.id}`, ["schedules"]);
  const setMode = (s: Schedule, mode: Schedule["mode"]) => toggle.mutate({ ...s, mode });
  const when = (s: Schedule) => (s.kind === "cron" ? `cron ${s.cron_expr}` : `${s.kind === "weekdays" ? "weekdays" : "daily"} at ${s.time_of_day}`) + ` (${s.timezone})`;
  return (
    <div className="space-y-5">
      <PageHeader title="Schedules" subtitle="Run a search profile on selected accounts – all in parallel, with random human-like delays." action={<Button onClick={() => setEditing("new")}>+ New schedule</Button>} />
      <WorkerBanner />
      {isLoading ? <p>Loading…</p> : data.length === 0 ? <Empty>No schedules yet.</Empty> : data.map((s) => {
        const last = runs.find((r) => r.schedule_id === s.id);
        return (
          <Card key={s.id}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div><span className="font-semibold">{s.name}</span> {!s.enabled && <Badge>disabled</Badge>}</div>
              <div className="flex flex-wrap gap-2">
                <Button small onClick={() => runNow(s.id)} disabled={run.isPending}>▶ Apply on all selected sites now</Button>
                <Button small variant="secondary" onClick={() => setEditing(s)}>Edit</Button>
                <Button small variant="secondary" onClick={() => toggle.mutate({ ...s, enabled: !s.enabled })}>{s.enabled ? "Pause" : "Enable"}</Button>
                <Button small variant="danger" onClick={() => confirm("Delete schedule?") && del.mutate(s.id)}>Delete</Button>
              </div>
            </div>
            <label className="mt-2 flex flex-wrap items-center gap-2 text-sm">
              <span className="font-medium">When a job matches:</span>
              <select className="rounded border border-slate-300 bg-white px-2 py-1" value={s.mode} disabled={toggle.isPending} onChange={(e) => setMode(s, e.target.value as Schedule["mode"])}>
                {(Object.keys(MODES) as Schedule["mode"][]).map((m) => <option key={m} value={m}>{MODES[m]}</option>)}
              </select>
              {toggle.isPending && toggle.variables?.id === s.id && <span className="text-slate-500">saving…</span>}
            </label>
            {toggle.variables?.id === s.id && <ErrorText error={toggle.error} />}
            <p className="mt-1 text-sm text-slate-600">{when(s)} · accounts: {s.account_ids.map((id) => accounts.find((a) => a.id === id)?.label ?? `#${id}`).join(", ")} · threshold {s.match_threshold} · parallel {s.max_concurrency}</p>
            <p className="text-xs text-slate-500">Next run: {fmt(s.next_run_at)}{last && <> · last run #{last.id} <Badge>{last.status}</Badge> <button className="underline" onClick={() => setWatch(last.id)}>view log</button>{last.status === "pending" && <> · <button className="text-red-700 underline" onClick={() => cancel.mutate(last.id)}>cancel</button></>}</>}</p>
            {run.variables === s.id && <ErrorText error={run.error} />}
          </Card>
        );
      })}
      <Card>
        <h3 className="mb-2 font-semibold">Run history</h3>
        {runs.length === 0 ? <p className="text-sm text-slate-500">No runs yet.</p> : runs.map((r) => (
          <div key={r.id} className="flex items-center justify-between border-b py-1 text-sm last:border-0">
            <span>#{r.id} · {data.find((s) => s.id === r.schedule_id)?.name} · {r.trigger} · {fmt(r.created_at)}</span>
            <span><Badge>{r.status}</Badge> <button className="ml-2 underline" onClick={() => setWatch(r.id)}>log</button>{r.status === "pending" && <button className="ml-2 text-red-700 underline" onClick={() => cancel.mutate(r.id)}>cancel</button>}</span>
          </div>
        ))}
      </Card>
      {editing && <ScheduleForm schedule={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
      {watch !== null && <RunLog runId={watch} onClose={() => setWatch(null)} />}
    </div>
  );
}

function ScheduleForm({ schedule, onClose }: { schedule: Schedule | null; onClose: () => void }) {
  const { data: profiles = [] } = useProfiles();
  const { data: accounts = [] } = useAccounts();
  const [f, setF] = useState({
    name: schedule?.name ?? "", search_profile_id: schedule?.search_profile_id ?? ("" as number | ""), account_ids: schedule?.account_ids ?? ([] as number[]),
    mode: schedule?.mode ?? "dry_run", kind: schedule?.kind ?? "daily", time_of_day: schedule?.time_of_day ?? "09:00", cron_expr: schedule?.cron_expr ?? "0 9 * * 1-5",
    timezone: schedule?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone, daily_cap: schedule?.daily_cap?.toString() ?? "",
    match_threshold: schedule?.match_threshold ?? 60, max_concurrency: schedule?.max_concurrency ?? 3, enabled: schedule?.enabled ?? true,
  });
  const save = useSend<Schedule, unknown>(schedule ? "PUT" : "POST", schedule ? `/schedules/${schedule.id}` : "/schedules", ["schedules"]);
  const toggle = (id: number) => setF({ ...f, account_ids: f.account_ids.includes(id) ? f.account_ids.filter((x) => x !== id) : [...f.account_ids, id] });
  const submit = () => save.mutate({
    ...f, search_profile_id: Number(f.search_profile_id), daily_cap: f.daily_cap === "" ? null : Number(f.daily_cap),
    time_of_day: f.kind === "cron" ? null : f.time_of_day, cron_expr: f.kind === "cron" ? f.cron_expr : null,
  }, { onSuccess: onClose });
  return (
    <Modal title={schedule ? "Edit schedule" : "New schedule"} onClose={onClose} wide>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Name"><input className={inputCls} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Search profile"><select className={inputCls} value={f.search_profile_id} onChange={(e) => setF({ ...f, search_profile_id: Number(e.target.value) })}><option value="">Select…</option>{profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
        <div className="md:col-span-2"><span className="mb-1 block text-sm font-medium">Accounts (run in parallel)</span>
          <div className="flex flex-wrap gap-3 text-sm">{accounts.map((a) => <label key={a.id}><input type="checkbox" className="mr-1" checked={f.account_ids.includes(a.id)} onChange={() => toggle(a.id)} />{a.label} <span className="text-slate-400">({a.site})</span></label>)}</div></div>
        <Field label="Mode"><select className={inputCls} value={f.mode} onChange={(e) => setF({ ...f, mode: e.target.value as Schedule["mode"] })}>{Object.entries(MODES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        <Field label="Repeat"><select className={inputCls} value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value as Schedule["kind"] })}><option value="daily">Daily</option><option value="weekdays">Weekdays (Mon–Fri)</option><option value="cron">Cron expression</option></select></Field>
        {f.kind === "cron" ? <Field label="Cron (min hour day month weekday)"><input className={inputCls} value={f.cron_expr} onChange={(e) => setF({ ...f, cron_expr: e.target.value })} /></Field>
          : <Field label="Time (24h)"><input type="time" className={inputCls} value={f.time_of_day} onChange={(e) => setF({ ...f, time_of_day: e.target.value })} /></Field>}
        <Field label="Timezone"><input className={inputCls} value={f.timezone} onChange={(e) => setF({ ...f, timezone: e.target.value })} /></Field>
        <Field label="Daily cap per account (blank = account's own cap)" hint="Never exceeds the account's cap (default 25)."><input type="number" min={1} className={inputCls} value={f.daily_cap} onChange={(e) => setF({ ...f, daily_cap: e.target.value })} /></Field>
        <Field label={`Apply only if match score ≥ ${f.match_threshold}`}><input type="range" min={0} max={100} className="w-full" value={f.match_threshold} onChange={(e) => setF({ ...f, match_threshold: Number(e.target.value) })} /></Field>
        <Field label="Max parallel accounts"><input type="number" min={1} max={8} className={inputCls} value={f.max_concurrency} onChange={(e) => setF({ ...f, max_concurrency: Number(e.target.value) })} /></Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.enabled} onChange={(e) => setF({ ...f, enabled: e.target.checked })} /> Enabled</label>
      </div>
      <ErrorText error={save.error} />
      <div className="mt-4 flex justify-end gap-2"><Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button disabled={!f.name || f.search_profile_id === "" || f.account_ids.length === 0 || save.isPending} onClick={submit}>Save</Button></div>
    </Modal>
  );
}

function RunLog({ runId, onClose }: { runId: number; onClose: () => void }) {
  const [lines, setLines] = useState<LogEntry[]>([]);
  const [status, setStatus] = useState("connecting");
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    setLines([]);
    const es = new EventSource(apiUrl(`/runs/${runId}/events`, true));
    es.addEventListener("log", (e) => { setStatus("live"); setLines((l) => [...l, JSON.parse((e as MessageEvent).data)]); });
    es.addEventListener("end", (e) => { setStatus(`finished (${JSON.parse((e as MessageEvent).data).status})`); es.close(); });
    es.onerror = () => setStatus((s) => (s.startsWith("finished") ? s : "disconnected"));
    return () => es.close();
  }, [runId]);
  useEffect(() => { box.current?.scrollTo({ top: box.current.scrollHeight }); }, [lines]);
  const color = { info: "text-slate-200", warn: "text-amber-300", error: "text-red-400" } as Record<string, string>;
  return (
    <Modal title={`Run #${runId} – ${status}`} onClose={onClose} wide>
      <div ref={box} className="h-96 overflow-y-auto rounded bg-slate-900 p-3 font-mono text-xs">
        {lines.length === 0 && <span className="text-slate-400">Waiting for the worker… (is it running?)</span>}
        {lines.map((l) => (
          <div key={l.id} className={color[l.level] ?? "text-slate-200"}>
            <span className="text-slate-500">{new Date(l.created_at + "Z").toLocaleTimeString()} </span>{l.message}
            {l.error_text && <span className="text-red-300"> — {l.error_text}</span>}
            {l.has_screenshot && <> <a className="underline" target="_blank" rel="noreferrer" href={apiUrl(`/logs/${l.id}/screenshot`, true)}>screenshot</a></>}
          </div>
        ))}
      </div>
    </Modal>
  );
}
