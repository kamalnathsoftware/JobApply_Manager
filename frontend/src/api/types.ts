export interface Contact { name?: string | null; email?: string | null; phone?: string | null; location?: string | null; linkedin?: string | null; github?: string | null; website?: string | null }
export interface Experience { company?: string | null; title?: string | null; location?: string | null; start?: string | null; end?: string | null; description?: string | null; highlights: string[] }
export interface Education { institution?: string | null; degree?: string | null; field?: string | null; start?: string | null; end?: string | null; grade?: string | null }
export interface Project { name?: string | null; description?: string | null; technologies: string[]; url?: string | null }
export interface ParsedResume {
  contact: Contact; headline?: string | null; summary?: string | null; current_title?: string | null; current_company?: string | null;
  total_experience_years?: number | null; skills: string[]; experience: Experience[]; education: Education[];
  projects: Project[]; certifications: string[]; languages: string[];
}
export interface Resume { id: number; label: string; original_filename: string; is_default: boolean; status: string; parse_error: string | null; created_at: string; profile: ParsedResume | null; profile_edited: boolean; auto_plan?: AutoPlan | null }
export interface AutoPlan { search_profile_id: number | null; schedule_id: number | null; created_profile: boolean; created_schedule: boolean; message: string }

export type Site = "naukri" | "linkedin" | "indeed" | "company";
export const SITES: Site[] = ["naukri", "linkedin", "indeed", "company"];
export interface Account { id: number; site: Site; label: string; login_email: string | null; resume_id: number | null; status: string; status_note: string | null; daily_cap: number; has_session: boolean; has_password: boolean; last_login_at: string | null }

export interface SearchProfile {
  id: number; name: string; keywords: string[]; location: string | null; experience_min: number | null; experience_max: number | null;
  salary_min: number | null; job_type: string | null; posted_within_days: number | null; excluded_companies: string[]; sites: string[];
  company_urls: string[]; account_id: number | null; max_results: number;
}
export interface Schedule {
  id: number; name: string; search_profile_id: number; account_ids: number[]; mode: "dry_run" | "review" | "auto";
  kind: "daily" | "weekdays" | "cron"; time_of_day: string | null; cron_expr: string | null; timezone: string; daily_cap: number | null;
  match_threshold: number; max_concurrency: number; enabled: boolean; next_run_at: string | null;
}
export interface Run { id: number; schedule_id: number; trigger: string; status: string; created_at: string; started_at: string | null; finished_at: string | null; summary: Record<string, unknown> | null; error: string | null }
export interface LogEntry { id: number; application_id: number | null; schedule_run_id: number | null; level: string; message: string; has_screenshot: boolean; error_text: string | null; created_at: string }
export interface Job { id: number; site: string; url: string; title: string; company: string | null; location: string | null; salary: string | null; experience: string | null; posted: string | null }
export interface Application {
  id: number; status: string; score: number | null; score_reasoning: string | null; approved: boolean; applied_at: string | null; status_note: string | null;
  needs_human_kind: string | null; pending_question: string | null; attempts: number; account_id: number; account_label: string | null;
  schedule_run_id: number | null; created_at: string; job: Job; description?: string | null;
}
export interface AnswerEntry { id: number; key: string; label: string; patterns: string[]; answer: string }
export interface Stats {
  by_status: Record<string, number>; applied_by_site: Record<string, number>; applied_per_day: ({ date: string } & Record<string, number | string>)[];
  accounts: { id: number; site: string; label: string; status: string; applied_today: number; cap: number }[];
  recent_runs: { id: number; schedule: string | null; status: string; started_at: string | null; summary: Record<string, number> | null }[];
  attention: { awaiting_approval: number; needs_human: number; accounts_need_login: number };
}
