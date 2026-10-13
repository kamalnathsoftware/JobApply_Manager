import { useQuery } from "@tanstack/react-query";
import { api, apiUrl } from "../api/client";
import type { Application, LogEntry } from "../api/types";
import { Badge, Modal, fmt } from "./ui";

export default function AppDetail({ id, onClose }: { id: number; onClose: () => void }) {
  const app = useQuery({ queryKey: ["application", id], queryFn: () => api<Application>(`/applications/${id}`) });
  const logs = useQuery({ queryKey: ["application-logs", id], queryFn: () => api<LogEntry[]>(`/applications/${id}/logs`) });
  const a = app.data;
  return (
    <Modal title={a ? `${a.job.title} – ${a.job.company ?? ""}` : "Application"} onClose={onClose} wide>
      {!a ? <p>Loading…</p> : (
        <div className="space-y-3 text-sm">
          <div className="flex flex-wrap items-center gap-2"><Badge>{a.status}</Badge><span>{a.job.site} via {a.account_label}</span>
            {a.score !== null && <span className="font-semibold">match {a.score}/100</span>}
            <a className="underline" href={a.job.url} target="_blank" rel="noreferrer">Open job ↗</a></div>
          {a.score_reasoning && <p className="rounded bg-slate-50 p-2"><b>Why this score:</b> {a.score_reasoning}</p>}
          {a.status_note && <p><b>Note:</b> {a.status_note}</p>}
          {a.pending_question && <p className="rounded bg-orange-50 p-2"><b>Question needing an answer:</b> {a.pending_question}</p>}
          <p className="text-slate-500">{[a.job.location, a.job.salary, a.job.experience, a.job.posted].filter(Boolean).join(" · ")}</p>
          {a.description && <details><summary className="cursor-pointer font-medium">Job description</summary><p className="mt-1 max-h-60 overflow-y-auto whitespace-pre-wrap text-xs">{a.description}</p></details>}
          <div>
            <h4 className="mb-1 font-medium">Activity log</h4>
            {(logs.data ?? []).length === 0 ? <p className="text-slate-500">No log entries.</p> : logs.data!.map((l) => (
              <div key={l.id} className={`border-b py-1 text-xs ${l.level === "error" ? "text-red-700" : l.level === "warn" ? "text-amber-700" : ""}`}>
                <span className="text-slate-400">{fmt(l.created_at)} </span>{l.message}{l.error_text && <span> — {l.error_text}</span>}
                {l.has_screenshot && <> · <a className="underline" target="_blank" rel="noreferrer" href={apiUrl(`/logs/${l.id}/screenshot`, true)}>screenshot</a></>}
              </div>
            ))}
          </div>
        </div>
      )}
    </Modal>
  );
}
