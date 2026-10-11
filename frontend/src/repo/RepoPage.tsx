// Packages or groups of the private repository (newest versions), with their deployment on the hosts.

import { Alert, Button, Card, Group, Loader, ScrollArea, Stack, Table, Text, TextInput, Title } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { IconChevronDown, IconChevronUp, IconPlus, IconSearch, IconSelector } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useMatch, useNavigate } from "react-router";

import { type Me, type RepoPackage, api, roleAtLeast } from "../api";
import { RelativeDate } from "../hosts/columns";
import { usePersistentState } from "../hosts/prefs";
import { GroupEditor } from "../ops/groups";
import PackageDetail from "./PackageDetail";
import { Deployment, PackageIcon } from "./common";

const packagesCount = (n: number) => `${n} paquet${n > 1 ? "s" : ""}`;

type SortKey = "name" | "hosts" | "pending" | "signed";
const SORTS: Record<SortKey, (p: RepoPackage) => string | number> = {
  name: (p) => (p.name || p.package).toLowerCase(),
  hosts: (p) => p.stats?.hosts ?? 0,
  pending: (p) => (p.stats?.pending ?? 0) + (p.stats?.errors ?? 0),
  signed: (p) => p.signature_date,
};

export default function RepoPage({ kind, me }: { kind: "package" | "group"; me: Me }) {
  const [creating, setCreating] = useState(false);
  const phone = useMediaQuery("(max-width: 48em)");
  const navigate = useNavigate();
  const base = kind === "group" ? "/groups" : "/packages";
  const selected = useMatch(`${base}/:name`)?.params.name;
  const [search, setSearch] = useState("");
  const [sort, setSort] = usePersistentState<{ key: SortKey; desc: boolean }>(`wwc.repo.${kind}.sort`,
    { key: "name", desc: false }, (v) => typeof v === "object" && v !== null && v.key in SORTS);
  const { data, error, isLoading } = useQuery({
    queryKey: ["packages", kind],
    queryFn: () => api.get<RepoPackage[]>(`/api/packages?kind=${kind}`),
    refetchInterval: 60_000,
  });

  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    const value = SORTS[sort.key];
    return (data ?? [])
      .filter((p) => !q || [p.package, p.name, p.description, p.editor, ...p.depends]
        .some((v) => v?.toLowerCase().includes(q)))
      .sort((a, b) => {
        const va = value(a), vb = value(b);
        const c = typeof va === "number" ? va - (vb as number) : String(va).localeCompare(String(vb), "fr");
        return sort.desc ? -c : c;
      });
  }, [data, search, sort]);

  const open = (p: RepoPackage) => navigate(`${base}/${encodeURIComponent(p.package)}`);
  const header = (key: SortKey, label: string) => (
    <Table.Th style={{ cursor: "pointer", whiteSpace: "nowrap", userSelect: "none" }}
              onClick={() => setSort(sort.key === key ? { key, desc: !sort.desc } : { key, desc: key !== "name" })}>
      <Group gap={4} wrap="nowrap">
        {label}
        {sort.key !== key ? <IconSelector size={14} opacity={0.4} />
          : sort.desc ? <IconChevronDown size={14} /> : <IconChevronUp size={14} />}
      </Group>
    </Table.Th>
  );
  const title = kind === "group" ? "Groupes" : "Paquets";

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>{title}</Title>
        <Group gap="sm">
          {data && <Text size="sm" c="dimmed">{shown.length} / {data.length}</Text>}
          {kind === "group" && roleAtLeast(me.user.role, "admin") && (
            <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setCreating(true)}>Nouveau groupe</Button>
          )}
        </Group>
      </Group>
      {creating && <GroupEditor onClose={() => setCreating(false)}
                                onSaved={(name) => navigate(`${base}/${encodeURIComponent(name)}`)} />}
      <TextInput placeholder={kind === "group" ? "Rechercher un groupe ou un paquet qu'il contient"
                   : "Rechercher : nom, paquet, éditeur, description"}
                 leftSection={<IconSearch size={16} />} size={phone ? "md" : "sm"}
                 value={search} onChange={(e) => setSearch(e.currentTarget.value)} />
      {isLoading && <Loader />}
      {error && <Alert color="red" title="Dépôt indisponible">{(error as Error).message}</Alert>}

      {phone ? (
        <Stack gap="xs">
          {shown.map((p) => (
            <Card key={p.package} withBorder padding="sm" radius="md" onClick={() => open(p)} style={{ cursor: "pointer" }}>
              <Group wrap="nowrap" align="flex-start">
                <PackageIcon icon={p.icon} group={kind === "group"} size={36} />
                <Stack gap={4} style={{ minWidth: 0, flex: 1 }}>
                  <Text fw={600} truncate>{p.name || p.package}</Text>
                  <Text size="sm" c="dimmed" truncate>
                    {kind === "group" ? packagesCount(p.depends.length) : `${p.package} · ${p.version}`}
                  </Text>
                  <Deployment stats={p.stats} />
                </Stack>
              </Group>
            </Card>
          ))}
        </Stack>
      ) : (
        <ScrollArea type="auto">
          <Table highlightOnHover stickyHeader fz="sm" verticalSpacing={6}>
            <Table.Thead>
              <Table.Tr>
                {header("name", kind === "group" ? "Groupe" : "Paquet")}
                <Table.Th>{kind === "group" ? "Contenu" : "Version"}</Table.Th>
                {kind === "package" && <Table.Th>Système</Table.Th>}
                {header("hosts", "Machines")}
                {header("pending", "Déploiement")}
                {header("signed", "Signé")}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {shown.map((p) => (
                <Table.Tr key={p.package} onClick={() => open(p)} style={{ cursor: "pointer" }}
                          bg={p.package === selected ? "var(--mantine-color-blue-light)" : undefined}>
                  <Table.Td>
                    <Group gap="sm" wrap="nowrap">
                      <PackageIcon icon={p.icon} group={kind === "group"} />
                      <Stack gap={0} style={{ minWidth: 0 }}>
                        <Text size="sm" fw={500} truncate>{p.name || p.package}</Text>
                        {p.name && <Text size="xs" c="dimmed" truncate>{p.package}</Text>}
                      </Stack>
                    </Group>
                  </Table.Td>
                  <Table.Td style={{ whiteSpace: "nowrap" }}>
                    {kind === "group" ? packagesCount(p.depends.length) : p.version}
                  </Table.Td>
                  {kind === "package" && (
                    <Table.Td>{[p.target_os, p.architecture].filter(Boolean).join(" · ")}</Table.Td>
                  )}
                  <Table.Td>{p.stats?.hosts ?? 0}</Table.Td>
                  <Table.Td><Deployment stats={p.stats} /></Table.Td>
                  <Table.Td style={{ whiteSpace: "nowrap" }}>
                    {p.signature_date && <RelativeDate iso={p.signature_date} />}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      )}
      <PackageDetail name={selected} base={base} me={me} onClose={() => navigate(base)} />
    </Stack>
  );
}
