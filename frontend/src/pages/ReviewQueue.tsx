import { useState } from "react";
import { useApplications, useSend } from "../api/hooks";
import type { Application } from "../api/types";
import AppDetail from "../components/AppDetail";
import { Badge, Button, Card, Empty, ErrorText, PageHeader } from "../components/ui";

export default function ReviewQueue() {
  const queued = useApplications("status=queued&limit=200");
  const human = useApplications("status=needs_human&limit=200");
  const [detail, setDetail] = useState<number | null>(null);
  const [picked, setPicked] = useState<number[]>([]);
  const approve = useSend<unknown, { ids: number[] }>("POST", "/applications/approve", ["applications", "stats"]);
  const reject = useSend<unknown, { ids: number[] }>("POST", "/applications/reject", ["applications", "stats"]);
  const items = queued.data?.items ?? [];
  const toggle = (id: number) => setPicked(picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id]);
  return (
    <div className="space-y-6">
      <PageHeader title="Review queue" subtitle="Approved jobs are submitted by the worker, within each account's daily cap." />
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold">Needs you ({human.data?.total ?? 0})</h3>
        </div>
        <p className="text-sm text-slate-500">The automation stopped here – an unknown question, or a login / CAPTCHA that only you can handle. It never guesses.</p>
        {(human.data?.items ?? []).length === 0 ? <Empty>Nothing needs your attention.</Empty> : human.data!.items.map((a) => <HumanCard key={a.id} a={a} onDetail={() => setDetail(a.id)} />)}
      </section>
      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-lg font-semibold">Awaiting approval ({queued.data?.total ?? 0})</h3>
          <div className="flex gap-2">
            <Button small variant="secondary" onClick={() => setPicked(picked.length === items.length ? [] : items.map((i) => i.id))}>{picked.length === items.length && items.length ? "Clear" : "Select all"}</Button>
            <Button small disabled={!picked.length || approve.isPending} onClick={() => approve.mutate({ ids: picked }, { onSuccess: () => setPicked([]) })}>Approve selected ({picked.length})</Button>
            <Button small variant="danger" disabled={!picked.length} onClick={() => reject.mutate({ ids: picked }, { onSuccess: () => setPicked([]) })}>Reject selected</Button>
          </div>
        </div>
        <ErrorText error={approve.error ?? reject.error} />
        {items.length === 0 ? <Empty>No jobs waiting. Use a schedule in <b>review</b> mode to fill this queue.</Empty> : items.map((a) => (
          <Card key={a.id} className={a.approved ? "opacity-60" : ""}>
            <div className="flex items-start gap-3">
              <input type="checkbox" className="mt-1" checked={picked.includes(a.id)} onChange={() => toggle(a.id)} disabled={a.approved} />
              <div className="flex-1">
                <div className="flex flex-wrap items-center gap-2"><button className="font-semibold underline-offset-2 hover:underline" onClick={() => setDetail(a.id)}>{a.job.title}</button>
                  <span className="text-sm text-slate-600">{a.job.company}</span><Badge>{a.job.site}</Badge>
                  <span className={`rounded px-1.5 text-xs font-bold ${(a.score ?? 0) >= 80 ? "bg-green-100 text-green-800" : "bg-amber-100 text-amber-800"}`}>{a.score}/100</span>
                  {a.approved && <Badge>approved – waiting for worker</Badge>}</div>
                <p className="mt-1 text-sm text-slate-600">{a.score_reasoning}</p>
                <p className="text-xs text-slate-400">{[a.job.location, a.job.salary, a.job.experience].filter(Boolean).join(" · ")} · via {a.account_label}{a.status_note ? ` · ${a.status_note}` : ""}</p>
              </div>
              {!a.approved && <div className="flex gap-2"><Button small onClick={() => approve.mutate({ ids: [a.id] })}>Approve</Button><Button small variant="secondary" onClick={() => reject.mutate({ ids: [a.id] })}>Reject</Button></div>}
            </div>
          </Card>
        ))}
      </section>
      {detail !== null && <AppDetail id={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}

function HumanCard({ a, onDetail }: { a: Application; onDetail: () => void }) {
  const [answer, setAnswer] = useState("");
  const [save, setSave] = useState(true);
  const send = useSend<unknown, { answer: string; save_to_bank: boolean }>("POST", `/applications/${a.id}/answer`, ["applications", "stats", "answers"]);
  const retry = useSend<unknown, void>("POST", `/applications/${a.id}/retry`, ["applications", "stats"]);
  const reject = useSend<unknown, { ids: number[] }>("POST", "/applications/reject", ["applications", "stats"]);
  const question = a.needs_human_kind === "unknown_question" || a.needs_human_kind === "unknown_field";
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2"><button className="font-semibold hover:underline" onClick={onDetail}>{a.job.title}</button><span className="text-sm text-slate-600">{a.job.company}</span><Badge>{a.job.site}</Badge><Badge>{a.needs_human_kind ?? "needs_human"}</Badge></div>
      <p className="mt-1 text-sm">{a.status_note}</p>
      {question && a.pending_question ? (
        <div className="mt-2 space-y-2 rounded bg-orange-50 p-3">
          <p className="text-sm"><b>Question:</b> {a.pending_question}</p>
          <input className="w-full rounded border border-slate-300 px-3 py-2 text-sm" placeholder="Your answer (e.g. 30 days)" value={answer} onChange={(e) => setAnswer(e.target.value)} />
          <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={save} onChange={(e) => setSave(e.target.checked)} /> Remember this answer for similar questions</label>
          <div className="flex gap-2"><Button small disabled={!answer || send.isPending} onClick={() => send.mutate({ answer, save_to_bank: save })}>Save answer & retry</Button>
            <Button small variant="secondary" onClick={() => reject.mutate({ ids: [a.id] })}>Skip this job</Button></div>
          <ErrorText error={send.error} />
        </div>
      ) : (
        <div className="mt-2 flex gap-2"><span className="text-sm text-slate-600">Resolve it on the site / Accounts page (e.g. re-login), then retry.</span>
          <Button small onClick={() => retry.mutate()}>Retry</Button><Button small variant="secondary" onClick={() => reject.mutate({ ids: [a.id] })}>Skip</Button></div>
      )}
    </Card>
  );
}
