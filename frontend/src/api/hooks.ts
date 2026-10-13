import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type { Account, AnswerEntry, Application, Resume, Run, Schedule, SearchProfile, Stats } from "./types";

export const useResumes = () => useQuery({ queryKey: ["resumes"], queryFn: () => api<Resume[]>("/resumes") });
export const useAccounts = (refetchInterval?: number) => useQuery({ queryKey: ["accounts"], queryFn: () => api<Account[]>("/accounts"), refetchInterval });
export const useProfiles = () => useQuery({ queryKey: ["profiles"], queryFn: () => api<SearchProfile[]>("/search-profiles") });
export const useSchedules = () => useQuery({ queryKey: ["schedules"], queryFn: () => api<Schedule[]>("/schedules") });
export const useRuns = (scheduleId?: number, refetchInterval?: number) =>
  useQuery({ queryKey: ["runs", scheduleId], queryFn: () => api<Run[]>(`/runs${scheduleId ? `?schedule_id=${scheduleId}` : ""}`), refetchInterval });
export const useAnswers = () => useQuery({ queryKey: ["answers"], queryFn: () => api<AnswerEntry[]>("/answer-bank") });
export const useStats = () => useQuery({ queryKey: ["stats"], queryFn: () => api<Stats>("/dashboard/stats"), refetchInterval: 15000 });
export const useApplications = (qs: string) =>
  useQuery({ queryKey: ["applications", qs], queryFn: () => api<{ total: number; items: Application[] }>(`/applications?${qs}`), refetchInterval: 10000 });

/** Mutation helper: sends JSON and invalidates the given query keys on success. */
export function useSend<T = unknown, B = unknown>(method: string, path: string | ((b: B) => string), invalidate: string[]) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: B) => api<T>(typeof path === "function" ? path(body) : path, { method, body: body === undefined ? undefined : JSON.stringify(body) }),
    onSuccess: () => invalidate.forEach((k) => qc.invalidateQueries({ queryKey: [k] })),
  });
}
