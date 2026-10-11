import {
  ActionIcon,
  Alert,
  Badge,
  Card,
  Group,
  Loader,
  ScrollArea,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import {
  IconCopy,
  IconDotsVertical,
  IconDownload,
  IconPackage,
  IconPlugConnected,
  IconRefresh,
  IconSearch,
} from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { type Host, api, hostName } from "../api";
import { type Action, useActionMenu } from "../components/ActionMenu";

const STATUS_COLORS: Record<string, string> = { OK: "green", ERROR: "red", "TO-UPGRADE": "orange", RUNNING: "blue" };

function copy(text: string, what: string) {
  navigator.clipboard
    .writeText(text)
    .then(() => notifications.show({ message: `${what} copié`, color: "green" }))
    .catch(() => notifications.show({ message: "Copie impossible (contexte non sécurisé ?)", color: "red" }));
}

function hostActions(h: Host): Action[] {
  const soon = { disabled: true, hint: "v0.4" };
  return [
    { key: "update", label: "Mettre à jour l'index", icon: <IconRefresh size={16} />, ...soon },
    { key: "upgrade", label: "Appliquer les mises à jour", icon: <IconDownload size={16} />, ...soon },
    { key: "install", label: "Installer un paquet…", icon: <IconPackage size={16} />, ...soon },
    { key: "wol", label: "Réveiller (Wake-on-LAN)", icon: <IconPlugConnected size={16} />, ...soon },
    { key: "copy-name", label: "Copier le nom", icon: <IconCopy size={16} />, onClick: () => copy(hostName(h), "Nom") },
    { key: "copy-uuid", label: "Copier l'UUID", icon: <IconCopy size={16} />, onClick: () => copy(h.uuid, "UUID") },
  ];
}

function Connected({ host }: { host: Host }) {
  const ok = host.reachable === "OK";
  return (
    <Badge color={ok ? "green" : "gray"} variant={ok ? "filled" : "light"} size="sm">
      {ok ? "Connectée" : "Déconnectée"}
    </Badge>
  );
}

function Status({ host }: { host: Host }) {
  if (!host.host_status) return null;
  return (
    <Badge color={STATUS_COLORS[host.host_status] ?? "gray"} variant="light" size="sm">
      {host.host_status}
    </Badge>
  );
}

function lastSeen(value?: string) {
  return value ? new Date(value).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—";
}

export default function Hosts() {
  const [search, setSearch] = useState("");
  const phone = useMediaQuery("(max-width: 48em)");
  const { bind, openFrom } = useActionMenu();
  const { data, error, isLoading } = useQuery({
    queryKey: ["hosts"],
    queryFn: () => api.get<Host[]>("/api/hosts"),
    refetchInterval: 30_000,
  });

  const hosts = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (data ?? [])
      .filter((h) => !q || [hostName(h), h.os_name, h.description, h.uuid].some((v) => v?.toLowerCase().includes(q)))
      .sort((a, b) => hostName(a).localeCompare(hostName(b)));
  }, [data, search]);

  const more = (h: Host) => (
    <ActionIcon variant="subtle" color="gray" size="lg" aria-label="Actions"
                onClick={(e) => openFrom(e, hostName(h), hostActions(h))}>
      <IconDotsVertical size={18} />
    </ActionIcon>
  );

  return (
    <Stack>
      <Group justify="space-between" wrap="nowrap">
        <Title order={2}>Machines</Title>
        {data && <Text c="dimmed" size="sm">{hosts.length} / {data.length}</Text>}
      </Group>
      <TextInput placeholder="Rechercher une machine, un OS…" leftSection={<IconSearch size={16} />}
                 value={search} onChange={(e) => setSearch(e.currentTarget.value)} size={phone ? "md" : "sm"} />
      {isLoading && <Loader />}
      {error && <Alert color="red" title="Inventaire indisponible">{(error as Error).message}</Alert>}

      {phone ? (
        <Stack gap="xs">
          {hosts.map((h) => (
            <Card key={h.uuid} withBorder padding="sm" radius="md" {...bind(hostName(h), hostActions(h))}
                  style={{ userSelect: "none", WebkitTouchCallout: "none" }}>
              <Group justify="space-between" wrap="nowrap" align="flex-start">
                <Stack gap={4} style={{ minWidth: 0 }}>
                  <Text fw={600} truncate>{hostName(h)}</Text>
                  <Text size="sm" c="dimmed" truncate>{h.os_name}</Text>
                  <Group gap={6}><Connected host={h} /><Status host={h} /></Group>
                </Stack>
                {more(h)}
              </Group>
            </Card>
          ))}
        </Stack>
      ) : (
        <ScrollArea>
          <Table highlightOnHover verticalSpacing="xs" miw={800}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Nom</Table.Th>
                <Table.Th>Système</Table.Th>
                <Table.Th>Connexion</Table.Th>
                <Table.Th>État</Table.Th>
                <Table.Th>Dernière remontée</Table.Th>
                <Table.Th>Agent</Table.Th>
                <Table.Th w={48} />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {hosts.map((h) => (
                <Table.Tr key={h.uuid} {...bind(hostName(h), hostActions(h))}>
                  <Table.Td fw={500}>{hostName(h)}</Table.Td>
                  <Table.Td>{h.os_name}</Table.Td>
                  <Table.Td><Connected host={h} /></Table.Td>
                  <Table.Td><Status host={h} /></Table.Td>
                  <Table.Td>{lastSeen(h.last_seen_on)}</Table.Td>
                  <Table.Td>{h.wapt_version}</Table.Td>
                  <Table.Td>{more(h)}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      )}
    </Stack>
  );
}
