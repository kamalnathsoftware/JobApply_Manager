import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api, apiUrl, ApiError } from "../api/client";
import { useResumes, useSend } from "../api/hooks";
import { Link } from "react-router-dom";
import type { AutoPlan, ParsedResume, Resume } from "../api/types";
import { Badge, Button, Card, Empty, ErrorText, Field, Modal, PageHeader, csv, inputCls } from "../components/ui";

export default function Resumes() {
  const { data = [], isLoading } = useResumes();
  const qc = useQueryClient();
  const file = useRef<HTMLInputElement>(null);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [editing, setEditing] = useState<Resume | null>(null);
  const [autoPlan, setAutoPlan] = useState(true);
  const [planNote, setPlanNote] = useState<AutoPlan | null>(null);
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const refreshPlan = () => ["profiles", "schedules"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  async function planNow(id: number) {
    setError(null);
    try { setPlanNote(await api<AutoPlan>(`/resumes/${id}/auto-plan?timezone=${encodeURIComponent(tz)}`, { method: "POST" })); refreshPlan(); }
    catch (e) { setError(e); }
  }
  const makeDefault = useSend<Resume, number>("POST", (id) => `/resumes/${id}/default`, ["resumes"]);
  const reparse = useSend<Resume, number>("POST", (id) => `/resumes/${id}/reparse`, ["resumes"]);
  const del = useSend<void, number>("DELETE", (id) => `/resumes/${id}`, ["resumes", "accounts"]);

  async function upload() {
    const f = file.current?.files?.[0];
    if (!f) return;
    setBusy(true); setError(null);
    const fd = new FormData();
    fd.append("file", f);
    if (label) fd.append("label", label);
    fd.append("auto_plan", String(autoPlan));
    fd.append("timezone", tz);
    try {
      const r = await api<Resume>("/resumes", { method: "POST", body: fd });
      setPlanNote(r.auto_plan ?? null); refreshPlan();
      setLabel(""); if (file.current) file.current.value = "";
      qc.invalidateQueries({ queryKey: ["resumes"] });
    } catch (e) { setError(e); } finally { setBusy(false); }
  }

  return (
    <div className="space-y-5">
      <PageHeader title="Resumes" subtitle="Upload PDF/DOCX. An AI model extracts structured data you can correct before it is used on forms." />
      <Card>
        <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto] md:items-end">
          <Field label="File (PDF or DOCX, ≤10 MB)"><input ref={file} type="file" accept=".pdf,.docx" className={inputCls} /></Field>
          <Field label="Label (optional)"><input className={inputCls} value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Backend CV" /></Field>
          <Button onClick={upload} disabled={busy}>{busy ? "Uploading & parsing…" : "Upload"}</Button>
        </div>
        <label className="mt-3 flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={autoPlan} onChange={(e) => setAutoPlan(e.target.checked)} />
          After parsing, automatically create a search profile (title, experience, location from the resume) and a daily 09:00 schedule in <b>review</b> mode
        </label>
        <ErrorText error={error} />
        {planNote && (
          <p className="mt-3 rounded bg-emerald-50 p-3 text-sm text-emerald-900">
            {planNote.message} {planNote.search_profile_id && <Link className="underline" to="/search-profiles">Search profiles</Link>}
            {planNote.schedule_id && <> · <Link className="underline" to="/schedules">Schedules</Link> · <Link className="underline" to="/review">Review queue</Link></>}
          </p>
        )}
      </Card>
      {isLoading ? <p>Loading…</p> : data.length === 0 ? <Empty>No resumes yet.</Empty> : data.map((r) => (
        <Card key={r.id}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <span className="font-semibold">{r.label}</span> {r.is_default && <span className="ml-1 text-amber-600" title="default">★ default</span>}
              <div className="text-xs text-slate-500">{r.original_filename}</div>
            </div>
            <div className="flex items-center gap-2"><Badge>{r.status}</Badge>{r.profile_edited && <Badge>edited</Badge>}</div>
          </div>
          {r.parse_error && <p className="mt-2 text-sm text-red-600">{r.parse_error}</p>}
          {r.profile && (
            <p className="mt-2 text-sm text-slate-600">
              {r.profile.contact.name} · {r.profile.current_title ?? "—"} · {r.profile.total_experience_years ?? "?"} yrs · {r.profile.skills.length} skills
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            {r.profile && <Button small variant="secondary" onClick={() => setEditing(r)}>Review / edit parsed data</Button>}
            {!r.is_default && <Button small variant="secondary" onClick={() => makeDefault.mutate(r.id)}>Make default</Button>}
            {r.profile && <Button small variant="secondary" onClick={() => planNow(r.id)}>Auto-create search &amp; schedule</Button>}
            <Button small variant="secondary" onClick={() => reparse.mutate(r.id)} disabled={reparse.isPending}>Re-parse</Button>
            <a className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100" href={apiUrl(`/resumes/${r.id}/file`, true)} target="_blank" rel="noreferrer">Download</a>
            <Button small variant="danger" onClick={() => confirm("Delete this resume?") && del.mutate(r.id)}>Delete</Button>
          </div>
          <ErrorText error={reparse.error instanceof ApiError ? reparse.error : null} />
        </Card>
      ))}
      {editing && <ProfileEditor resume={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function ProfileEditor({ resume, onClose }: { resume: Resume; onClose: () => void }) {
  const [p, setP] = useState<ParsedResume>(structuredClone(resume.profile!));
  const [skills, setSkills] = useState(p.skills.join(", "));
  const save = useSend<Resume, ParsedResume>("PUT", `/resumes/${resume.id}/profile`, ["resumes"]);
  const set = <K extends keyof ParsedResume>(k: K, v: ParsedResume[K]) => setP({ ...p, [k]: v });
  const text = (v: string | null | undefined, on: (s: string) => void, ph?: string) => <input className={inputCls} value={v ?? ""} placeholder={ph} onChange={(e) => on(e.target.value)} />;
  return (
    <Modal title={`Parsed data – ${resume.label}`} onClose={onClose} wide>
      <div className="space-y-4">
        <div className="grid gap-3 md:grid-cols-2">
          {(["name", "email", "phone", "location", "linkedin", "github", "website"] as const).map((k) => (
            <Field key={k} label={k}>{text(p.contact[k], (s) => set("contact", { ...p.contact, [k]: s || null }))}</Field>
          ))}
          <Field label="Current title">{text(p.current_title, (s) => set("current_title", s || null))}</Field>
          <Field label="Current company">{text(p.current_company, (s) => set("current_company", s || null))}</Field>
          <Field label="Total experience (years)"><input type="number" step="0.5" className={inputCls} value={p.total_experience_years ?? ""} onChange={(e) => set("total_experience_years", e.target.value === "" ? null : Number(e.target.value))} /></Field>
        </div>
        <Field label="Summary"><textarea className={inputCls} rows={3} value={p.summary ?? ""} onChange={(e) => set("summary", e.target.value || null)} /></Field>
        <Field label="Skills (comma separated)"><textarea className={inputCls} rows={2} value={skills} onChange={(e) => { setSkills(e.target.value); set("skills", csv(e.target.value)); }} /></Field>
        <Section title="Experience" onAdd={() => set("experience", [...p.experience, { highlights: [] }])}>
          {p.experience.map((x, i) => (
            <Row key={i} onRemove={() => set("experience", p.experience.filter((_, j) => j !== i))}>
              {text(x.title, (s) => upd("experience", i, { title: s }), "Title")}{text(x.company, (s) => upd("experience", i, { company: s }), "Company")}
              {text(x.start, (s) => upd("experience", i, { start: s }), "Start")}{text(x.end, (s) => upd("experience", i, { end: s }), "End / Present")}
              <textarea className={`${inputCls} md:col-span-2`} rows={2} placeholder="Description" value={x.description ?? ""} onChange={(e) => upd("experience", i, { description: e.target.value })} />
            </Row>
          ))}
        </Section>
        <Section title="Education" onAdd={() => set("education", [...p.education, {}])}>
          {p.education.map((x, i) => (
            <Row key={i} onRemove={() => set("education", p.education.filter((_, j) => j !== i))}>
              {text(x.institution, (s) => upd("education", i, { institution: s }), "Institution")}{text(x.degree, (s) => upd("education", i, { degree: s }), "Degree")}
              {text(x.field, (s) => upd("education", i, { field: s }), "Field")}{text(x.end, (s) => upd("education", i, { end: s }), "Year")}
            </Row>
          ))}
        </Section>
        <ErrorText error={save.error} />
        <div className="flex justify-end gap-2"><Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button disabled={save.isPending} onClick={() => save.mutate(p, { onSuccess: onClose })}>Save corrections</Button></div>
      </div>
    </Modal>
  );
  function upd<K extends "experience" | "education">(k: K, i: number, patch: Partial<ParsedResume[K][number]>) {
    set(k, p[k].map((x, j) => (j === i ? { ...x, ...patch } : x)) as ParsedResume[K]);
  }
}

const Section = ({ title, onAdd, children }: { title: string; onAdd: () => void; children: React.ReactNode }) => (
  <div><div className="mb-2 flex items-center justify-between"><h4 className="font-medium">{title}</h4><Button small variant="secondary" onClick={onAdd}>+ Add</Button></div><div className="space-y-2">{children}</div></div>
);
const Row = ({ children, onRemove }: { children: React.ReactNode; onRemove: () => void }) => (
  <div className="grid gap-2 rounded border border-slate-200 p-2 md:grid-cols-2">{children}<Button small variant="danger" className="md:col-span-2 md:w-24" onClick={onRemove}>Remove</Button></div>
);
