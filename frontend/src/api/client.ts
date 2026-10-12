const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

const ACCESS = "jam_access";
const REFRESH = "jam_refresh";

export const tokens = {
  get access() { return localStorage.getItem(ACCESS); },
  get refresh() { return localStorage.getItem(REFRESH); },
  set(access: string, refresh: string) {
    localStorage.setItem(ACCESS, access);
    localStorage.setItem(REFRESH, refresh);
  },
  clear() {
    localStorage.removeItem(ACCESS);
    localStorage.removeItem(REFRESH);
  },
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function raw(path: string, init: RequestInit, auth: boolean): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (auth && tokens.access) headers.set("Authorization", `Bearer ${tokens.access}`);
  return fetch(`${BASE}/api${path}`, { ...init, headers });
}

let refreshing: Promise<boolean> | null = null;
function tryRefresh(): Promise<boolean> {
  refreshing ??= (async () => {
    const rt = tokens.refresh;
    if (!rt) return false;
    const r = await raw("/auth/refresh", { method: "POST", body: JSON.stringify({ refresh_token: rt }) }, false);
    if (!r.ok) return false;
    const t = await r.json();
    tokens.set(t.access_token, t.refresh_token);
    return true;
  })().finally(() => { refreshing = null; });
  return refreshing;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res = await raw(path, init, true);
  if (res.status === 401 && tokens.refresh && (await tryRefresh())) res = await raw(path, init, true);
  if (res.status === 401) tokens.clear();
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : res.statusText;
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}
