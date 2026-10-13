import { useState } from "react";
import { useAccounts, useResumes, useSend } from "../api/hooks";
import { SITES, type Account, type Site } from "../api/types";
import { Badge, Button, Card, Empty, ErrorText, Field, Modal, PageHeader, inputCls } from "../components/ui";

const HELP: Record<string, string> = {
  naukri: "A visible browser opens on the machine running the backend. Log in (OTP included); it closes itself when done.",
  linkedin: "Log in (and pass any verification) in the browser window; it closes itself when logged in.",
  indeed: "Log in in the browser window; it closes itself when logged in.",
  company: "Optional: log in to a career portal yourself, then close the window to save the session.",
};

export default function Accounts() {
  const { data = [], isLoading } = useAccounts(3000);
  const { data: resumes = [] } = useResumes();
  const [editing, setEditing] = useState<Account | "new" | null>(null);
  const login = useSend<Account, number>("POST", (id) => `/accounts/${id}/login/start`, ["accounts"]);
  const clear = useSend<Account, number>("POST", (id) => `/accounts/${id}/session/clear`, ["accounts"]);
  const del = useSend<void, number>("DELETE", (id) => `/accounts/${id}`, ["accounts"]);
  return (
    <div className="space-y-5">
      <PageHeader title="Site accounts" subtitle="One account per login. Use different emails/resumes per site. Passwords and cookies are encrypted at rest." action={<Button onClick={() => setEditing("new")}>+ Add account</Button>} />
      <p className="rounded bg-amber-50 p-3 text-sm text-amber-900">Assisted login opens a real browser window, so the backend must run on your own computer (not in Docker). The app never solves CAPTCHAs: if a site asks, you do it in that window.</p>
      {isLoading ? <p>Loading…</p> : data.length === 0 ? <Empty>No accounts yet.</Empty> : data.map((a) => (
        <Card key={a.id}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div><span className="font-semibold">{a.label}</span> <span className="text-sm text-slate-500">{a.site} · {a.login_email ?? "no email set"}</span></div>
            <Badge>{a.status}</Badge>
          </div>
          <p className="mt-1 text-sm text-slate-600">
            Resume: {resumes.find((r) => r.id === a.resume_id)?.label ?? "default resume"} · cap {a.daily_cap}/day · session {a.has_session ? "saved" : "none"}
          </p>
          {a.status_note && <p className="mt-1 text-sm text-orange-700">{a.status_note}</p>}
          {a.status === "login_in_progress" && <p className="mt-1 text-sm text-blue-700">A browser window should be open on the backend machine…</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            <Button small disabled={a.status === "login_in_progress"} onClick={() => login.mutate(a.id)}>{a.has_session ? "Re-login" : "Log in (assisted)"}</Button>
            <Button small variant="secondary" onClick={() => setEditing(a)}>Edit</Button>
            {a.has_session && <Button small variant="secondary" onClick={() => clear.mutate(a.id)}>Forget session</Button>}
            <Button small variant="danger" onClick={() => confirm("Delete this account and its application history?") && del.mutate(a.id)}>Delete</Button>
          </div>
          <p className="mt-2 text-xs text-slate-500">{HELP[a.site]}</p>
          {login.variables === a.id && <ErrorText error={login.error} />}
        </Card>
      ))}
      {editing && <AccountForm account={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function AccountForm({ account, onClose }: { account: Account | null; onClose: () => void }) {
  const { data: resumes = [] } = useResumes();
  const [f, setF] = useState({ site: (account?.site ?? "naukri") as Site, label: account?.label ?? "", login_email: account?.login_email ?? "", password: "", resume_id: account?.resume_id ?? ("" as number | ""), daily_cap: account?.daily_cap ?? 25 });
  const save = useSend<Account, Record<string, unknown>>(account ? "PATCH" : "POST", account ? `/accounts/${account.id}` : "/accounts", ["accounts"]);
  const submit = () => {
    const body: Record<string, unknown> = { label: f.label, login_email: f.login_email || null, daily_cap: Number(f.daily_cap) };
    if (!account) body.site = f.site;
    if (f.password) body.password = f.password;
    if (f.resume_id !== "") body.resume_id = Number(f.resume_id); else if (account) body.clear_resume = true;
    save.mutate(body, { onSuccess: onClose });
  };
  return (
    <Modal title={account ? "Edit account" : "Add account"} onClose={onClose}>
      <div className="space-y-3">
        {!account && <Field label="Site"><select className={inputCls} value={f.site} onChange={(e) => setF({ ...f, site: e.target.value as Site })}>{SITES.map((s) => <option key={s}>{s}</option>)}</select></Field>}
        <Field label="Label"><input className={inputCls} value={f.label} onChange={(e) => setF({ ...f, label: e.target.value })} placeholder="e.g. Naukri – personal email" /></Field>
        <Field label="Login email"><input className={inputCls} value={f.login_email} onChange={(e) => setF({ ...f, login_email: e.target.value })} /></Field>
        <Field label="Password (optional, stored encrypted)" hint="Not needed for assisted login. Leave blank to keep the current value."><input type="password" autoComplete="new-password" className={inputCls} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
        <Field label="Resume for this account"><select className={inputCls} value={f.resume_id} onChange={(e) => setF({ ...f, resume_id: e.target.value === "" ? "" : Number(e.target.value) })}><option value="">Default resume</option>{resumes.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}</select></Field>
        <Field label="Max applications per day" hint="Keep this modest (default 25) to respect site limits."><input type="number" min={1} max={200} className={inputCls} value={f.daily_cap} onChange={(e) => setF({ ...f, daily_cap: Number(e.target.value) })} /></Field>
        <ErrorText error={save.error} />
        <div className="flex justify-end gap-2"><Button variant="secondary" onClick={onClose}>Cancel</Button><Button disabled={!f.label || save.isPending} onClick={submit}>Save</Button></div>
      </div>
    </Modal>
  );
}
