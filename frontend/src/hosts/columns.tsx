// Catalogue of the host columns: label, group, how to display and how to sort each value.

import { Badge, Group, Text, Tooltip } from "@mantine/core";
import type { ReactNode } from "react";

import type { Host } from "../api";
import { rfc3339 } from "../dates";

export type SortKind = "text" | "number" | "date" | "bool";

export interface Column {
  id: string;
  label: string;
  group: "Identité" | "Réseau" | "Utilisateurs" | "Système" | "Matériel" | "WAPT";
  sort: SortKind;
  value: (h: Host) => string | number | boolean | null;
  render?: (h: Host) => ReactNode;
  nowrap?: boolean;
}

const STATUS_COLORS: Record<string, string> = {
  OK: "green", ERROR: "red", WARNING: "orange", "TO-UPGRADE": "orange", RUNNING: "blue",
  "NEED-INSTALL": "orange", "NEED-UPGRADE": "orange", "NEED-REMOVE": "orange", UNKNOWN: "gray",
};
const STATUS_LABELS: Record<string, string> = {
  OK: "OK", ERROR: "Erreur", WARNING: "Alerte", "TO-UPGRADE": "À mettre à jour", RUNNING: "En cours",
  "NEED-INSTALL": "À installer", "NEED-UPGRADE": "À mettre à jour", "NEED-REMOVE": "À désinstaller",
  UNKNOWN: "Inconnu",
};

export function StatusBadge({ value }: { value: string }) {
  if (!value) return null;
  return (
    <Badge color={STATUS_COLORS[value] ?? "gray"} variant="light" size="sm">
      {STATUS_LABELS[value] ?? value}
    </Badge>
  );
}

export function ConnectedBadge({ connected }: { connected: boolean }) {
  return (
    <Badge color={connected ? "green" : "gray"} variant={connected ? "filled" : "light"} size="sm">
      {connected ? "Connectée" : "Déconnectée"}
    </Badge>
  );
}

/** "il y a 5 min", with the exact RFC 3339 date in a tooltip. */
export function RelativeDate({ iso }: { iso: string }) {
  if (!iso) return <Text c="dimmed" span>—</Text>;
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  const label =
    minutes < 1 ? "à l'instant"
    : minutes < 60 ? `il y a ${minutes} min`
    : minutes < 48 * 60 ? `il y a ${Math.round(minutes / 60)} h`
    : `il y a ${Math.round(minutes / 1440)} j`;
  return (
    <Tooltip label={rfc3339(iso)} openDelay={300}>
      <Text span size="sm">{label}</Text>
    </Tooltip>
  );
}

const count = (n: number, color: string) => (n ? <Badge color={color} variant="light" size="sm">{n}</Badge> : null);

export const COLUMNS: Column[] = [
  { id: "name", label: "Nom", group: "Identité", sort: "text", value: (h) => h.name,
    render: (h) => <Text fw={500} size="sm">{h.name}</Text>, nowrap: true },
  { id: "description", label: "Description", group: "Identité", sort: "text", value: (h) => h.description },
  { id: "dnsdomain", label: "Domaine", group: "Identité", sort: "text", value: (h) => h.dnsdomain },
  { id: "main_ip", label: "Adresse IP", group: "Réseau", sort: "text", nowrap: true,
    value: (h) => h.main_ip.split(".").map((p) => p.padStart(3, "0")).join("."), render: (h) => h.main_ip },
  { id: "ips", label: "Adresses IP", group: "Réseau", sort: "text", value: (h) => h.ips.join(", ") },
  { id: "mac", label: "Adresse MAC", group: "Réseau", sort: "text", value: (h) => h.mac, nowrap: true },
  { id: "last_user", label: "Dernier utilisateur", group: "Utilisateurs", sort: "text", value: (h) => h.last_user },
  { id: "users", label: "Sessions ouvertes", group: "Utilisateurs", sort: "text", value: (h) => h.users.join(", ") },
  { id: "os_name", label: "Système", group: "Système", sort: "text", value: (h) => h.os_name },
  { id: "os_release", label: "Édition", group: "Système", sort: "text", value: (h) => h.os_release },
  { id: "os_version", label: "Version", group: "Système", sort: "text", value: (h) => h.os_version, nowrap: true },
  { id: "os_architecture", label: "Architecture", group: "Système", sort: "text", value: (h) => h.os_architecture },
  { id: "last_boot", label: "Dernier démarrage", group: "Système", sort: "date", value: (h) => h.last_boot,
    render: (h) => <RelativeDate iso={h.last_boot} />, nowrap: true },
  { id: "manufacturer", label: "Fabricant", group: "Matériel", sort: "text", value: (h) => h.manufacturer },
  { id: "model", label: "Modèle", group: "Matériel", sort: "text", value: (h) => h.model },
  { id: "serial", label: "N° de série", group: "Matériel", sort: "text", value: (h) => h.serial, nowrap: true },
  { id: "cpu", label: "Processeur", group: "Matériel", sort: "text", value: (h) => h.cpu },
  { id: "memory_gb", label: "Mémoire", group: "Matériel", sort: "number", value: (h) => h.memory_gb,
    render: (h) => (h.memory_gb == null ? "" : `${h.memory_gb} Go`), nowrap: true },
  { id: "connected", label: "Connexion", group: "WAPT", sort: "bool", value: (h) => h.connected,
    render: (h) => <ConnectedBadge connected={h.connected} /> },
  { id: "status", label: "État", group: "WAPT", sort: "text", value: (h) => h.status,
    render: (h) => <StatusBadge value={h.status} /> },
  { id: "audit_status", label: "Audit", group: "WAPT", sort: "text", value: (h) => h.audit_status,
    render: (h) => <StatusBadge value={h.audit_status} /> },
  { id: "pending", label: "Mises à jour", group: "WAPT", sort: "number", value: (h) => h.pending,
    render: (h) => count(h.pending, "orange") },
  { id: "errors", label: "Erreurs", group: "WAPT", sort: "number", value: (h) => h.errors,
    render: (h) => count(h.errors, "red") },
  { id: "last_seen", label: "Dernière remontée", group: "WAPT", sort: "date", value: (h) => h.last_seen,
    render: (h) => <RelativeDate iso={h.last_seen} />, nowrap: true },
  { id: "wapt_version", label: "Agent", group: "WAPT", sort: "text", value: (h) => h.wapt_version, nowrap: true },
];

export const COLUMN_BY_ID = Object.fromEntries(COLUMNS.map((c) => [c.id, c]));

export const DEFAULT_COLUMNS = ["name", "connected", "status", "os_name", "last_user", "main_ip", "last_seen"];

// --- Sorting ------------------------------------------------------------------------------------------------

export interface SortState {
  column: string;
  desc: boolean;
}

/** Default order: connected hosts first, then by name. */
export const DEFAULT_SORT: SortState = { column: "connected", desc: true };

function compareValues(a: unknown, b: unknown, kind: SortKind): number {
  const empty = (v: unknown) => v === null || v === undefined || v === "";
  if (empty(a) || empty(b)) return empty(a) === empty(b) ? 0 : empty(a) ? 1 : -1; // empty values last
  switch (kind) {
    case "number":
      return (a as number) - (b as number);
    case "date":
      return new Date(a as string).getTime() - new Date(b as string).getTime();
    case "bool":
      return Number(a) - Number(b);
    default:
      return String(a).localeCompare(String(b), "fr", { numeric: true, sensitivity: "base" });
  }
}

export function sortHosts(hosts: Host[], sort: SortState): Host[] {
  const col = COLUMN_BY_ID[sort.column] ?? COLUMN_BY_ID.connected;
  const byName = (a: Host, b: Host) => a.name.localeCompare(b.name, "fr", { numeric: true });
  return [...hosts].sort((a, b) => {
    const va = col.value(a), vb = col.value(b);
    const empty = (v: unknown) => v === null || v === "";
    // empty values stay last whatever the direction
    if (empty(va) !== empty(vb)) return empty(va) ? 1 : -1;
    const c = compareValues(va, vb, col.sort);
    return (sort.desc ? -c : c) || byName(a, b);
  });
}

export function Cell({ column, host }: { column: Column; host: Host }) {
  const content = column.render ? column.render(host) : column.value(host);
  return <Group gap={4} wrap="nowrap">{content as ReactNode}</Group>;
}
