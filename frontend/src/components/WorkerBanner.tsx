import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useSend } from "../api/hooks";
import { Button } from "./ui";

export default function WorkerBanner() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["worker"], queryFn: () => api<{ alive: boolean; age_s: number | null }>("/system/worker"), refetchInterval: 4000 });
  const start = useSend<{ started: boolean }, undefined>("POST", "/system/worker/start", ["worker"]);
  if (!data) return null;
  if (data.alive) return <p className="rounded bg-emerald-50 p-3 text-sm text-emerald-900">● Worker is running – runs start within a few seconds.</p>;
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded bg-red-50 p-3 text-sm text-red-900">
      <span>● Worker is <b>not running</b>, so runs stay “pending”. Start it here, or in a terminal: <code>python -m app.workers.main</code></span>
      <Button small disabled={start.isPending} onClick={() => start.mutate(undefined, { onSuccess: () => setTimeout(() => qc.invalidateQueries({ queryKey: ["worker"] }), 6000) })}>
        {start.isPending ? "Starting…" : start.isSuccess ? "Starting – wait a few seconds…" : "Start worker"}
      </Button>
    </div>
  );
}
