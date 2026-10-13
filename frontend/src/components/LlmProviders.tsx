import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { Badge, Button, Card, ErrorText, inputCls } from "./ui";

interface Provider { provider: string; enabled: boolean; priority: number; model: string; default_model: string; base_url: string; has_key: boolean; env_key: boolean; needs_key: boolean }
interface View { providers: Provider[]; source: "env" | "ui"; env: { provider: string; configured: boolean; usable: string[] } }
type Row = Provider & { api_key: string };
interface TestResult { ok: boolean; provider?: string; model?: string; error?: string }

const LABEL: Record<string, string> = { gemini: "Google Gemini (free tier)", groq: "Groq (free tier)", ollama: "Ollama (local, free)", anthropic: "Anthropic Claude (paid)" };

export default function LlmProviders() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["llm"], queryFn: () => api<View>("/llm/providers") });
  const [rows, setRows] = useState<Row[]>([]);
  const [results, setResults] = useState<Record<string, TestResult>>({});
  const [chainResult, setChainResult] = useState<TestResult | null>(null);
  useEffect(() => { if (data) setRows(data.providers.map((p) => ({ ...p, api_key: "" }))); }, [data]);

  const save = useMutation({
    mutationFn: () => api<View>("/llm/providers", { method: "PUT", body: JSON.stringify(rows.map((r, i) => ({
      provider: r.provider, enabled: r.enabled, priority: i, model: r.model || null, base_url: r.base_url || null, api_key: r.api_key === "" ? null : r.api_key.trim() === "-" ? "" : r.api_key,
    }))) }),
    onSuccess: (v) => { qc.setQueryData(["llm"], v); qc.invalidateQueries({ queryKey: ["system"] }); setResults({}); },
  });
  const reset = useMutation({ mutationFn: () => api<View>("/llm/providers", { method: "DELETE" }), onSuccess: (v) => { qc.setQueryData(["llm"], v); setResults({}); } });
  const test = async (provider?: string) => {
    const r = await api<TestResult>(`/llm/test${provider ? `?provider=${provider}` : ""}`, { method: "POST" });
    provider ? setResults((x) => ({ ...x, [provider]: r })) : setChainResult(r);
  };
  const upd = (i: number, patch: Partial<Row>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const move = (i: number, d: -1 | 1) => { const j = i + d; if (j < 0 || j >= rows.length) return; const n = [...rows]; [n[i], n[j]] = [n[j], n[i]]; setRows(n); };

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">AI providers</h3>
        <Badge>{data?.source === "ui" ? "saved in app" : "from .env"}</Badge>
      </div>
      <p className="mb-3 text-sm text-slate-500">
        Enabled providers are tried <b>top to bottom</b>; if one fails (rate limit, denied key, offline…) the next one is used.
        Keys saved here are encrypted and apply immediately – no restart needed.
        {data?.source === "env" && <> Currently using <code>.env</code>: {data.env.provider || "none"} ({data.env.configured ? "usable" : "not configured"}).</>}
      </p>
      <div className="space-y-2">
        {rows.map((r, i) => (
          <div key={r.provider} className={`rounded border p-3 ${r.enabled ? "border-slate-300" : "border-slate-200 bg-slate-50 opacity-80"}`}>
            <div className="flex flex-wrap items-center gap-3">
              <input type="checkbox" checked={r.enabled} onChange={(e) => upd(i, { enabled: e.target.checked })} />
              <span className="font-medium">{LABEL[r.provider] ?? r.provider}</span>
              {r.enabled && <span className="text-xs text-slate-500">priority {rows.filter((x, k) => k <= i && x.enabled).length}</span>}
              <span className="ml-auto flex gap-1">
                <Button small variant="secondary" onClick={() => move(i, -1)} disabled={i === 0}>↑</Button>
                <Button small variant="secondary" onClick={() => move(i, 1)} disabled={i === rows.length - 1}>↓</Button>
                <Button small variant="secondary" onClick={() => test(r.provider)}>Test</Button>
              </span>
            </div>
            <div className="mt-2 grid gap-2 md:grid-cols-3">
              {r.needs_key ? (
                <input type="password" autoComplete="off" className={inputCls} value={r.api_key} onChange={(e) => upd(i, { api_key: e.target.value })}
                  placeholder={r.has_key ? "key saved (type a new one to replace, '-' to remove)" : r.env_key ? "using key from .env (or paste to override)" : "paste API key"} />
              ) : (
                <input className={inputCls} value={r.base_url} onChange={(e) => upd(i, { base_url: e.target.value })} placeholder="http://localhost:11434/v1" />
              )}
              <input className={inputCls} value={r.model} onChange={(e) => upd(i, { model: e.target.value })} placeholder={`model (default ${r.default_model})`} />
              <div className="text-sm">
                {results[r.provider] && (results[r.provider].ok
                  ? <span className="text-green-700">✓ works ({results[r.provider].model})</span>
                  : <span className="break-words text-red-600">✗ {results[r.provider].error}</span>)}
              </div>
            </div>
          </div>
        ))}
      </div>
      <p className="mt-2 text-xs text-slate-500">“Test” uses the values currently <i>saved</i> – press Save first after changing a key or model.</p>
      <ErrorText error={save.error ?? reset.error} />
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button onClick={() => save.mutate()} disabled={save.isPending}>Save providers</Button>
        <Button variant="secondary" onClick={() => test()}>Test the whole chain</Button>
        {data?.source === "ui" && <Button variant="secondary" onClick={() => confirm("Forget saved providers and use .env again?") && reset.mutate()}>Reset to .env</Button>}
        {save.isSuccess && <span className="text-sm text-green-700">Saved.</span>}
        {chainResult && (chainResult.ok ? <span className="text-sm text-green-700">✓ answered by {chainResult.provider}</span> : <span className="text-sm text-red-600">✗ {chainResult.error}</span>)}
      </div>
    </Card>
  );
}
