// Audit journal of the console: every unlock, action and its result, by user (the WAPT server only sees "admin").

import { Alert, Badge, Button, Card, Group, Loader, ScrollArea, Stack, Table, Text, TextInput, Title,
  Tooltip } from "@mantine/core";
import { useDebouncedValue, useMediaQuery } from "@mantine/hooks";
import { IconSearch } from "@tabler/icons-react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";

import { type JournalEntry, api } from "../api";
import { rfc3339 } from "../dates";

const LABELS: Record<string, string> = {
  unlock: "Déverrouillage de la clé", lock: "Verrouillage de la clé",
  update: "Mise à jour de l'index", upgrade: "Mises à jour", install: "Installation", inventory: "Remontée d'inventaire",
  audit: "Audit", cancel: "Annulation des tâches", wol: "Wake-on-LAN", remove: "Désinstallation", forget: "Oubli",
  description: "Description", restart_agent: "Redémarrage de l'agent", reboot: "Redémarrage", shutdown: "Extinction",
};

const when = (at: number) => rfc3339(at);

function Targets({ e }: { e: JournalEntry }) {
  if (!e.targets.length) return null;
  const names = e.targets.map((t) => t.name);
  const shown = names.slice(0, 3).join(", ") + (names.length > 3 ? ` +${names.length - 3}` : "");
  return <Tooltip label={names.join(", ")} multiline maw={400} disabled={names.length <= 3}><Text size="sm">{shown}</Text></Tooltip>;
}

function What({ e }: { e: JournalEntry }) {
  return (
    <Stack gap={0}>
      <Text size="sm" fw={500}>{LABELS[e.action] ?? e.action}</Text>
      {e.params.packages && <Text size="xs" c="dimmed">{e.params.packages.join(", ")}{e.params.force ? " (forcé)" : ""}</Text>}
      {e.params.description && <Text size="xs" c="dimmed">« {e.params.description} »</Text>}
    </Stack>
  );
}

const Result = ({ e }: { e: JournalEntry }) => (
  <Tooltip label={e.detail} disabled={!e.detail} multiline maw={400}>
    <Badge color={e.ok ? "green" : "red"} variant="light" size="sm">{e.ok ? "OK" : "Échec"}</Badge>
  </Tooltip>
);

export default function JournalPage() {
  const phone = useMediaQuery("(max-width: 48em)");
  const [user, setUser] = useState("");
  const [host, setHost] = useState("");
  const [userQ] = useDebouncedValue(user.trim(), 400);
  const [hostQ] = useDebouncedValue(host.trim(), 400);
  const { data, error, isLoading, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: ["journal", userQ, hostQ],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ limit: "100" });
      if (pageParam) params.set("before", String(pageParam));
      if (userQ) params.set("username", userQ);
      if (hostQ) params.set("host", hostQ);
      return api.get<JournalEntry[]>(`/api/journal?${params}`);
    },
    getNextPageParam: (last) => (last.length === 100 ? last[last.length - 1].id : undefined),
    refetchInterval: 30_000,
  });
  const entries = data?.pages.flat() ?? [];

  return (
    <Stack gap="md">
      <Stack gap={0}>
        <Title order={2}>Journal</Title>
        <Text size="sm" c="dimmed">Actions menées depuis la console, par utilisateur.</Text>
      </Stack>
      <Group gap="xs" grow={!!phone}>
        <TextInput placeholder="Utilisateur (exact)" value={user} onChange={(e) => setUser(e.currentTarget.value)}
                   leftSection={<IconSearch size={16} />} />
        <TextInput placeholder="UUID de machine" value={host} onChange={(e) => setHost(e.currentTarget.value)}
                   leftSection={<IconSearch size={16} />} />
      </Group>
      {isLoading && <Loader />}
      {error && <Alert color="red">{(error as Error).message}</Alert>}
      {data && !entries.length && <Text c="dimmed">Aucune entrée.</Text>}

      {phone ? (
        <Stack gap="xs">
          {entries.map((e) => (
            <Card key={e.id} withBorder radius="md" padding="sm">
              <Group justify="space-between" wrap="nowrap" align="flex-start">
                <What e={e} />
                <Result e={e} />
              </Group>
              <Targets e={e} />
              <Text size="xs" c="dimmed">{when(e.at)} · {e.user}</Text>
              {!e.ok && e.detail && <Text size="xs" c="red">{e.detail}</Text>}
            </Card>
          ))}
        </Stack>
      ) : (
        <ScrollArea type="auto">
          <Table fz="sm" verticalSpacing={6} striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Date</Table.Th><Table.Th>Utilisateur</Table.Th><Table.Th>Action</Table.Th>
                <Table.Th>Machines</Table.Th><Table.Th>Résultat</Table.Th><Table.Th>Détail</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {entries.map((e) => (
                <Table.Tr key={e.id}>
                  <Table.Td style={{ whiteSpace: "nowrap" }}>{when(e.at)}</Table.Td>
                  <Table.Td>
                    <Text size="sm">{e.user}</Text>
                    <Text size="xs" c="dimmed">{e.role} · {e.ip}</Text>
                  </Table.Td>
                  <Table.Td><What e={e} /></Table.Td>
                  <Table.Td><Targets e={e} /></Table.Td>
                  <Table.Td><Result e={e} /></Table.Td>
                  <Table.Td><Text size="xs" c="dimmed" lineClamp={2}>{e.detail}</Text></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      )}
      {hasNextPage && (
        <Button variant="default" onClick={() => void fetchNextPage()} loading={isFetchingNextPage}>Plus ancien</Button>
      )}
    </Stack>
  );
}
