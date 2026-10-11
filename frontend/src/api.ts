// Backend API client: session cookie, CSRF token on requests that change state, login redirect on 401.

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

let csrfToken = "";

export function setCsrfToken(token: string) {
  csrfToken = token;
}

/** Login error returned by the OIDC callback (`/?auth_error=...`): no automatic redirect then, or it would loop. */
export const authError = new URLSearchParams(window.location.search).get("auth_error");

export function loginUrl(): string {
  const next = window.location.pathname + window.location.search;
  return `/auth/login?next=${encodeURIComponent(next.startsWith("/?auth_error") ? "/" : next)}`;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken;
  const resp = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (resp.status === 401 && !authError) {
    window.location.assign(loginUrl());
    throw new ApiError(401, "redirection vers la connexion");
  }
  const data = await resp.json().catch(() => null);
  if (!resp.ok) throw new ApiError(resp.status, data?.detail ?? `HTTP ${resp.status}`);
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
};

// --- Types of the backend answers ---------------------------------------------------------------------------

export type Role = "viewer" | "operator" | "admin";

export interface Me {
  user: { username: string; name: string; email: string; role: Role; groups: string[] };
  csrf: string;
  wapt_url: string;
}

export interface WaptStatus {
  url: string;
  hosts: number;
  connected: number;
}

export interface Host {
  uuid: string;
  computer_fqdn?: string;
  computer_name?: string;
  description?: string;
  os_name?: string;
  os_version?: string;
  reachable?: string;
  host_status?: string;
  last_seen_on?: string;
  wapt_version?: string;
  connected_users?: string[] | string;
}

export function hostName(h: Host): string {
  return h.computer_fqdn || h.computer_name || h.description || h.uuid;
}
