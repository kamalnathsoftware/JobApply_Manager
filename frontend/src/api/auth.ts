import { api, tokens } from "./client";

export interface User { id: number; email: string; full_name: string | null }

export async function login(email: string, password: string): Promise<void> {
  const t = await api<{ access_token: string; refresh_token: string }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  tokens.set(t.access_token, t.refresh_token);
}

export const register = (email: string, password: string, full_name?: string) =>
  api<User>("/auth/register", { method: "POST", body: JSON.stringify({ email, password, full_name }) });

export const me = () => api<User>("/auth/me");
