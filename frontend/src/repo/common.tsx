import { Badge, Group, Image, Tooltip } from "@mantine/core";
import { IconFolders, IconPackage } from "@tabler/icons-react";
import { useState } from "react";

import type { DeploymentStats } from "../api";

/** Package icon from the repository (through the backend), or a generic one. */
export function PackageIcon({ icon, group, size = 28, store }: {
  icon: string; group?: boolean; size?: number; store?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  if (!icon || failed) {
    const Generic = group ? IconFolders : IconPackage;
    return <Generic size={size} stroke={1.5} color="var(--mantine-color-dimmed)" style={{ flexShrink: 0 }} />;
  }
  return <Image src={`/api/icons/${icon}.png${store ? "?source=store" : ""}`} w={size} h={size} fit="contain" alt="" onError={() => setFailed(true)}
                style={{ flexShrink: 0 }} />;
}

export function Deployment({ stats }: { stats?: DeploymentStats }) {
  if (!stats || !stats.hosts) return <Badge variant="default" size="sm" tt="none">aucune machine</Badge>;
  return (
    <Group gap={4} wrap="nowrap">
      <Tooltip label="Installé et à jour"><Badge color="green" variant="light" size="sm">{stats.ok}</Badge></Tooltip>
      {stats.pending > 0 && <Tooltip label="À installer ou mettre à jour">
        <Badge color="orange" variant="light" size="sm">{stats.pending}</Badge></Tooltip>}
      {stats.errors > 0 && <Tooltip label="En erreur"><Badge color="red" variant="light" size="sm">{stats.errors}</Badge></Tooltip>}
    </Group>
  );
}

export function formatSize(bytes: number | null): string {
  if (bytes == null) return "";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} Ko`;
  return `${(bytes / 1024 / 1024).toFixed(1)} Mo`;
}
