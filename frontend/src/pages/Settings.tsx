import { useState } from "react";
import { useAnswers, useSend } from "../api/hooks";
import { api } from "../api/client";
import { useQuery } from "@tanstack/react-query";
import type { AnswerEntry } from "../api/types";
import { Button, Card, Empty, ErrorText, Field, PageHeader, csv, inputCls } from "../components/ui";
import { useAuth } from "../hooks/useAuth";

type Suggestion = { key: string; label: string; patterns: string[] };

export default function Settings() {
  const { user } = useAuth();
  const { data: bank = [] } = useAnswers();
  const { data: suggestions = [] } = useQuery({ queryKey: ["suggestions"], queryFn: () => api<Suggestion[]>("/answer-bank/suggestions") });
  const [draft, setDraft] = useState({ key: "custom", label: "", patterns: "", answer: "" });
  const add = useSend<AnswerEntry, unknown>("POST", "/answer-bank", ["answers"]);
  const upd = useSend<AnswerEntry, AnswerEntry>("PUT", (e) => `/answer-bank/${e.id}`, ["answers"]);
  const del = useSend<void, number>("DELETE", (id) => `/answer-bank/${id}`, ["answers"]);
  const unused = suggestions.filter((s) => !bank.some((b) => b.key === s.key));
  return (
    <div className="space-y-5">
      <PageHeader title="Settings" subtitle={`Signed in as ${user?.email}`} />
      <Card>
        <h3 className="font-semibold">Answer bank</h3>
        <p className="mb-3 text-sm text-slate-500">Used to answer screening questions automatically. A question matches an entry when it contains any of its patterns. Unknown questions are never guessed – they appear in the Review queue.</p>
        {bank.length === 0 && <Empty>No saved answers yet.</Empty>}
        {bank.map((e) => <Row key={e.id} e={e} onSave={(x) => upd.mutate(x)} onDelete={() => del.mutate(e.id)} />)}
        <ErrorText error={upd.error ?? del.error} />
        {unused.length > 0 && (
          <div className="mt-4"><p className="mb-1 text-sm font-medium">Quick add</p><div className="flex flex-wrap gap-2">
            {unused.map((s) => <Button key={s.key} small variant="secondary" onClick={() => setDraft({ key: s.key, label: s.label, patterns: s.patterns.join(", "), answer: "" })}>{s.label}</Button>)}</div></div>
        )}
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <Field label="Label"><input className={inputCls} value={draft.label} onChange={(e) => setDraft({ ...draft, label: e.target.value })} placeholder="Notice period" /></Field>
          <Field label="Answer"><input className={inputCls} value={draft.answer} onChange={(e) => setDraft({ ...draft, answer: e.target.value })} placeholder="30 days" /></Field>
          <div className="md:col-span-2"><Field label="Match when question contains (comma separated)"><input className={inputCls} value={draft.patterns} onChange={(e) => setDraft({ ...draft, patterns: e.target.value })} placeholder="notice period, how soon can you join" /></Field></div>
        </div>
        <ErrorText error={add.error} />
        <Button className="mt-3" disabled={!draft.label || !draft.answer || !draft.patterns || add.isPending}
          onClick={() => add.mutate({ key: draft.key, label: draft.label, patterns: csv(draft.patterns), answer: draft.answer }, { onSuccess: () => setDraft({ key: "custom", label: "", patterns: "", answer: "" }) })}>Add answer</Button>
      </Card>
      <Card>
        <h3 className="font-semibold">Server configuration</h3>
        <p className="text-sm text-slate-600">API keys, the Fernet key, browser mode (headless), pacing delays and the Indeed domain are set in the <code>.env</code> file on the machine running the backend/worker – never in the browser.</p>
      </Card>
    </div>
  );
}

function Row({ e, onSave, onDelete }: { e: AnswerEntry; onSave: (e: AnswerEntry) => void; onDelete: () => void }) {
  const [answer, setAnswer] = useState(e.answer);
  return (
    <div className="mb-2 grid items-center gap-2 border-b pb-2 md:grid-cols-[1fr_1fr_auto]">
      <div><div className="text-sm font-medium">{e.label}</div><div className="text-xs text-slate-500">matches: {e.patterns.join(", ")}</div></div>
      <input className={inputCls} value={answer} onChange={(x) => setAnswer(x.target.value)} />
      <div className="flex gap-2"><Button small disabled={answer === e.answer} onClick={() => onSave({ ...e, answer })}>Save</Button><Button small variant="danger" onClick={onDelete}>Delete</Button></div>
    </div>
  );
}
