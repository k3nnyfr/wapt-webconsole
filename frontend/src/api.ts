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

/** Flattened host, as returned by the backend (``wapt/hosts.py: flatten``). */
export interface Host {
  uuid: string;
  name: string;
  computer_name: string;
  description: string;
  dnsdomain: string;
  main_ip: string;
  ips: string[];
  mac: string;
  last_user: string;
  users: string[];
  os_name: string;
  os_version: string;
  os_release: string;
  os_architecture: string;
  platform: string;
  manufacturer: string;
  model: string;
  serial: string;
  cpu: string;
  memory_gb: number | null;
  last_boot: string;
  connected: boolean;
  status: string;
  audit_status: string;
  pending: number;
  errors: number;
  last_seen: string;
  wapt_version: string;
  reboot_allowed: boolean;
  shutdown_allowed: boolean;
}

export interface HostsAnswer {
  hosts: Host[];
  read_at: number;
  server: string;
}

export interface HostDetail {
  host: Host;
  hardware: {
    bios_vendor: string;
    bios_version: string;
    bios_date: string;
    os_installed_on: string;
    drives: { name: string; filesystem: string; size_gb: number | null; free_gb: number | null; free_percent: number | null }[];
    gateways: string[];
    networks: string[];
  };
  host_package: {
    version: string;
    depends: string[];
    conflicts: string[];
    signer: string;
    signature_date: string;
  } | null;
}

export interface HostPackage {
  package: string;
  name: string;
  version: string;
  section: string;
  maturity: string;
  description: string;
  install_status: string;
  install_date: string;
  install_output: string;
  explicit_by: string;
  audit_status: string;
  audit_on: string;
  audit_output: string;
}

export interface Software {
  name: string;
  version: string;
  publisher: string;
  install_date: string;
  system_component: boolean;
  key: string;
}
