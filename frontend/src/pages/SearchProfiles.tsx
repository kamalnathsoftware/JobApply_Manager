import { useState } from "react";
import { useProfiles, useSend } from "../api/hooks";
import { SITES, type SearchProfile } from "../api/types";
import { Button, Card, Empty, ErrorText, Field, Modal, PageHeader, csv, inputCls } from "../components/ui";

const num = (s: string) => (s === "" ? null : Number(s));

export default function SearchProfiles() {
  const { data = [], isLoading } = useProfiles();
  const [editing, setEditing] = useState<SearchProfile | "new" | null>(null);
  const del = useSend<void, number>("DELETE", (id) => `/search-profiles/${id}`, ["profiles", "schedules"]);
  return (
    <div className="space-y-5">
      <PageHeader title="Search profiles" subtitle="What to look for. A schedule combines a profile with site accounts." action={<Button onClick={() => setEditing("new")}>+ New profile</Button>} />
      {isLoading ? <p>Loading…</p> : data.length === 0 ? <Empty>No search profiles yet.</Empty> : data.map((p) => (
        <Card key={p.id}>
          <div className="flex items-center justify-between"><span className="font-semibold">{p.name}</span>
            <span className="flex gap-2"><Button small variant="secondary" onClick={() => setEditing(p)}>Edit</Button><Button small variant="danger" onClick={() => confirm("Delete profile and its schedules?") && del.mutate(p.id)}>Delete</Button></span></div>
          <p className="mt-1 text-sm text-slate-600">
            {p.keywords.join(", ")} · {p.location ?? "any location"} · exp {p.experience_min ?? "0"}–{p.experience_max ?? "∞"} yrs · within {p.posted_within_days ?? "any"} days · sites: {p.sites.join(", ") || "all"}
          </p>
          {p.excluded_companies.length > 0 && <p className="text-xs text-slate-500">Excluding: {p.excluded_companies.join(", ")}</p>}
        </Card>
      ))}
      {editing && <ProfileForm profile={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function ProfileForm({ profile, onClose }: { profile: SearchProfile | null; onClose: () => void }) {
  const [f, setF] = useState({
    name: profile?.name ?? "", keywords: profile?.keywords.join(", ") ?? "", location: profile?.location ?? "",
    experience_min: profile?.experience_min?.toString() ?? "", experience_max: profile?.experience_max?.toString() ?? "",
    salary_min: profile?.salary_min?.toString() ?? "", job_type: profile?.job_type ?? "", posted_within_days: profile?.posted_within_days?.toString() ?? "7",
    excluded: profile?.excluded_companies.join(", ") ?? "", sites: profile?.sites ?? ["naukri"], company_urls: profile?.company_urls.join("\n") ?? "", max_results: profile?.max_results ?? 25,
  });
  const save = useSend<SearchProfile, unknown>(profile ? "PUT" : "POST", profile ? `/search-profiles/${profile.id}` : "/search-profiles", ["profiles"]);
  const toggle = (s: string) => setF({ ...f, sites: f.sites.includes(s) ? f.sites.filter((x) => x !== s) : [...f.sites, s] });
  const submit = () => save.mutate({
    name: f.name, keywords: csv(f.keywords), location: f.location || null, experience_min: num(f.experience_min), experience_max: num(f.experience_max),
    salary_min: num(f.salary_min), job_type: f.job_type || null, posted_within_days: num(f.posted_within_days), excluded_companies: csv(f.excluded),
    sites: f.sites, company_urls: f.company_urls.split("\n").map((x) => x.trim()).filter(Boolean), max_results: Number(f.max_results),
  }, { onSuccess: onClose });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <Modal title={profile ? "Edit search profile" : "New search profile"} onClose={onClose} wide>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Name"><input className={inputCls} value={f.name} onChange={set("name")} /></Field>
        <Field label="Keywords (comma separated)"><input className={inputCls} value={f.keywords} onChange={set("keywords")} placeholder="python, fastapi" /></Field>
        <Field label="Location"><input className={inputCls} value={f.location} onChange={set("location")} placeholder="Bengaluru" /></Field>
        <Field label="Job type"><select className={inputCls} value={f.job_type} onChange={set("job_type")}><option value="">Any</option><option value="full_time">Full time</option><option value="contract">Contract</option><option value="part_time">Part time</option><option value="internship">Internship</option></select></Field>
        <Field label="Experience min (yrs)"><input type="number" className={inputCls} value={f.experience_min} onChange={set("experience_min")} /></Field>
        <Field label="Experience max (yrs)"><input type="number" className={inputCls} value={f.experience_max} onChange={set("experience_max")} /></Field>
        <Field label="Min salary (per year)"><input type="number" className={inputCls} value={f.salary_min} onChange={set("salary_min")} /></Field>
        <Field label="Posted within (days)"><input type="number" min={1} max={90} className={inputCls} value={f.posted_within_days} onChange={set("posted_within_days")} /></Field>
        <Field label="Exclude companies (comma separated)"><input className={inputCls} value={f.excluded} onChange={set("excluded")} /></Field>
        <Field label="Max jobs per account per run"><input type="number" min={1} max={200} className={inputCls} value={f.max_results} onChange={set("max_results")} /></Field>
        <div className="md:col-span-2"><span className="mb-1 block text-sm font-medium">Sites to include</span>
          <div className="flex gap-4 text-sm">{SITES.map((s) => <label key={s}><input type="checkbox" className="mr-1" checked={f.sites.includes(s)} onChange={() => toggle(s)} />{s}</label>)}</div></div>
        {f.sites.includes("company") && <div className="md:col-span-2"><Field label="Company apply URLs (one per line)" hint="The generic adapter opens each URL and fills the form; unknown fields, logins and CAPTCHAs stop for you."><textarea className={inputCls} rows={4} value={f.company_urls} onChange={set("company_urls")} /></Field></div>}
      </div>
      <ErrorText error={save.error} />
      <div className="mt-4 flex justify-end gap-2"><Button variant="secondary" onClick={onClose}>Cancel</Button><Button disabled={!f.name || !f.keywords || save.isPending} onClick={submit}>Save</Button></div>
    </Modal>
  );
}
