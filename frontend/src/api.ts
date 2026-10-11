// Backend API client: session cookie, CSRF token on requests that change state, login redirect on 401.

export class ApiError extends Error {
  /** ``detail`` of the answer when it is structured (e.g. why a deletion is refused) */
  constructor(public status: number, message: string, public detail?: Record<string, unknown>) {
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

function errorOf(status: number, data: { detail?: unknown } | null): ApiError {
  const detail = data?.detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const d = detail as Record<string, unknown>;
    return new ApiError(status, String(d.message ?? `HTTP ${status}`), d);
  }
  if (Array.isArray(detail)) return new ApiError(status, detail.map((e) => e?.msg ?? String(e)).join(" ; "));
  return new ApiError(status, typeof detail === "string" ? detail : `HTTP ${status}`);
}

/** Multipart upload with progress (fetch cannot report upload progress). */
export function upload<T>(path: string, file: File, onProgress: (fraction: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    xhr.setRequestHeader("X-CSRF-Token", csrfToken);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      let data = null;
      try { data = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as T);
      else reject(errorOf(xhr.status, data));
    };
    xhr.onerror = () => reject(new ApiError(0, "réseau indisponible"));
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
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
  if (!resp.ok) throw errorOf(resp.status, data);
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body ?? {}),
  delete: <T>(path: string) => request<T>("DELETE", path),
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

export interface DeploymentStats {
  hosts: number;
  ok: number;
  pending: number;
  errors: number;
}

/** Repository package or group (``wapt/repository.py: summary``). */
export interface RepoPackage {
  package: string;
  name: string;
  version: string;
  section: string;
  description: string;
  categories: string[];
  editor: string;
  target_os: string;
  architecture: string;
  maturity: string;
  locale: string;
  depends: string[];
  conflicts: string[];
  signer: string;
  signature_date: string;
  size: number | null;
  filename: string;
  icon: string;
  homepage: string;
  licence: string;
  stats?: DeploymentStats;
}

export interface PackageDetail {
  package: RepoPackage;
  versions: RepoPackage[];
  hosts: { uuid: string; name: string; version: string; install_status: string; install_date: string;
           audit_status: string }[];
}

export const ROLES: Role[] = ["viewer", "operator", "admin"];
export const roleAtLeast = (role: Role, required: Role) => ROLES.indexOf(role) >= ROLES.indexOf(required);

export interface SigningStatus {
  server_key: boolean;          // a key is stored on the console server (optional)
  unlocked: boolean;
  expires_in: number;
  ttl: number;
  identity: { cn?: string; fingerprint?: string };
}

export type ActionName =
  | "update" | "upgrade" | "install" | "inventory" | "audit" | "cancel" | "wol"
  | "remove" | "forget" | "description" | "restart_agent" | "reboot" | "shutdown";

export interface ActionResult {
  action: ActionName;
  label: string;
  message: string;
  reached: { uuid: string; name: string }[];
  skipped: { uuid: string; name: string }[];
}

export interface AgentTask {
  id: number;
  description: string;
  summary: string;
  progress: number | null;
  runstatus: string;
  created: string | null;
  started: string | null;
  finished: string | null;
  created_by: string;
  logs: string;
}

export interface AgentTasks {
  running: AgentTask | null;
  pending: AgentTask[];
  done: AgentTask[];
  errors: AgentTask[];
  cancelled: AgentTask[];
}

export interface JournalEntry {
  id: number;
  at: number;
  user: string;
  role: Role;
  ip: string;
  action: string;
  targets: { uuid: string; name: string }[];
  params: { packages?: string[]; description?: string; force?: boolean };
  ok: boolean;
  detail: string;
}

export interface AssignmentChange {
  uuid: string;
  name: string;
  connected: boolean;
  version: string | null;
  depends: string[];
  conflicts: string[];
  new_depends: string[];
  new_conflicts: string[];
  changed: boolean;
}

export interface AssignmentPreview {
  changes: AssignmentChange[];
  unknown: string[];
}

export interface AssignmentResult {
  published: { uuid: string; name: string; connected: boolean; version: string; previous: string | null }[];
  unchanged: { uuid: string; name: string }[];
  conflicts: { uuid: string; name: string; expected: string | null; found: string | null }[];
  failed: { uuid: string; name: string; error: string }[];
  upgrade: string | null;
}

export interface CleanupCandidate {
  package: string;
  version: string;
  target: string;
  newest: string;
  size: number;
  package_uuid: string;
  filename: string;
}

export interface PackageUsage {
  dependents: string[];
  hosts: string[];
}

export interface StoreTarget {
  target: string;
  version: string;
  repo_version: string | null;
  state: "absent" | "update" | "ok";
  size: number;
}

/** Store package useful to the fleet (``store.py: catalogue``), ``name`` without prefix. */
export interface StoreRow {
  name: string;
  store_package: string;
  title: string;
  description: string;
  editor: string;
  categories: string[];
  licence: string;
  restricted: boolean;
  icon: string;
  homepage: string;
  version: string;
  signature_date: string;
  targets: StoreTarget[];
  state: "absent" | "update" | "ok";
  size: number;
}

export interface StoreCatalogue {
  rows: StoreRow[];
  prefix: string;
  fleet: string[];
  modified: string;
  trusted: boolean;
}

export interface StorePlanItem {
  store_package: string;
  target_name: string;
  version: string;
  target: string;
  filename: string;
  size: number;
  reason: "requested" | "dependency";
  repo_version: string | null;
}

export interface StorePlan {
  items: StorePlanItem[];
  refused: string[];
  missing: string[];
  size: number;
  prefix: string;
}

export interface JobItem {
  name: string;
  version: string;
  target: string;
  size: number;
  reason: string;
  status: "waiting" | "downloading" | "signing" | "uploading" | "done" | "error";
  progress: number;
  error: string;
  imported_version: string;
}

export interface Job {
  id: string;
  user: string;
  kind: string;
  items: JobItem[];
  created: number;
  status: "running" | "done" | "failed";
  message: string;
  finished: number | null;
}
