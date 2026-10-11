// Main page: inventory of the hosts, with indicators that act as quick filters, configurable and sortable columns,
// a table on a computer or tablet and cards on a phone.

import {
  ActionIcon,
  Alert,
  Badge,
  Card,
  Group,
  Loader,
  ScrollArea,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import {
  IconChevronDown,
  IconChevronUp,
  IconCopy,
  IconDotsVertical,
  IconDownload,
  IconId,
  IconPackage,
  IconPlugConnected,
  IconRefresh,
  IconSearch,
  IconSelector,
  IconSortAscending,
  IconSortDescending,
} from "@tabler/icons-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useMatch, useNavigate } from "react-router";

import { type Host, type HostsAnswer, type Me, api } from "../api";
import { type Action, useActionMenu } from "../components/ActionMenu";
import { useLiveHosts } from "../live";
import ColumnsPicker from "./ColumnsPicker";
import Filters, { ActiveFilters, type FilterValues, matchesFilters } from "./Filters";
import HostDetail from "./HostDetail";
import {
  COLUMNS,
  COLUMN_BY_ID,
  Cell,
  ConnectedBadge,
  DEFAULT_COLUMNS,
  DEFAULT_SORT,
  RelativeDate,
  type SortState,
  StatusBadge,
  sortHosts,
} from "./columns";
import { usePersistentState } from "./prefs";

type QuickFilter = "all" | "connected" | "upgrade" | "error";

const QUICK_FILTERS: { id: QuickFilter; label: string; color: string; test: (h: Host) => boolean }[] = [
  { id: "all", label: "Machines", color: "blue", test: () => true },
  { id: "connected", label: "Connectées", color: "green", test: (h) => h.connected },
  { id: "upgrade", label: "Mises à jour", color: "orange", test: (h) => h.pending > 0 || h.status === "TO-UPGRADE" },
  { id: "error", label: "En erreur", color: "red",
    test: (h) => h.errors > 0 || h.status === "ERROR" || h.audit_status === "ERROR" },
];

const SEARCHED = ["name", "description", "last_user", "main_ip", "os_name", "serial", "model", "dnsdomain"] as const;

function copy(text: string, what: string) {
  navigator.clipboard
    .writeText(text)
    .then(() => notifications.show({ message: `${what} copié`, color: "green" }))
    .catch(() => notifications.show({ message: "Copie impossible", color: "red" }));
}

function hostActions(h: Host, open: (uuid: string) => void): Action[] {
  const soon = { disabled: true, hint: "v0.4" };
  return [
    { key: "open", label: "Ouvrir la fiche", icon: <IconId size={16} />, onClick: () => open(h.uuid) },
    { key: "update", label: "Mettre à jour l'index", icon: <IconRefresh size={16} />, ...soon },
    { key: "upgrade", label: "Appliquer les mises à jour", icon: <IconDownload size={16} />, ...soon },
    { key: "install", label: "Installer un paquet…", icon: <IconPackage size={16} />, ...soon },
    { key: "wol", label: "Réveiller (Wake-on-LAN)", icon: <IconPlugConnected size={16} />, ...soon },
    { key: "copy-name", label: "Copier le nom", icon: <IconCopy size={16} />, onClick: () => copy(h.name, "Nom") },
    ...(h.main_ip
      ? [{ key: "copy-ip", label: "Copier l'adresse IP", icon: <IconCopy size={16} />,
           onClick: () => copy(h.main_ip, "Adresse IP") }]
      : []),
    { key: "copy-uuid", label: "Copier l'UUID", icon: <IconCopy size={16} />, onClick: () => copy(h.uuid, "UUID") },
  ];
}

function Indicator({ label, value, color, active, compact, onClick }: {
  label: string; value: number; color: string; active: boolean; compact: boolean; onClick: () => void;
}) {
  return (
    <UnstyledButton onClick={onClick} aria-pressed={active}>
      <Card withBorder radius="md" padding={compact ? 6 : "sm"} ta={compact ? "center" : undefined}
            style={{ borderColor: active ? `var(--mantine-color-${color}-filled)` : undefined,
                     borderWidth: active ? 2 : undefined }}>
        {!compact && <Text size="xs" c="dimmed" truncate>{label}</Text>}
        <Text size={compact ? "lg" : "xl"} fw={700} c={value && color !== "blue" ? color : undefined}>{value}</Text>
        {compact && <Text fz={11} c="dimmed" truncate>{label}</Text>}
      </Card>
    </UnstyledButton>
  );
}

function SortIcon({ column, sort }: { column: string; sort: SortState }) {
  if (sort.column !== column) return <IconSelector size={14} opacity={0.4} />;
  return sort.desc ? <IconChevronDown size={14} /> : <IconChevronUp size={14} />;
}

export default function HostsPage({ me }: { me: Me }) {
  const phone = useMediaQuery("(max-width: 48em)");
  const queryClient = useQueryClient();
  const { bind, openFrom } = useActionMenu();
  const selected = useMatch("/hosts/:uuid")?.params.uuid;
  const navigate = useNavigate();
  const open = (uuid: string) => navigate(`/hosts/${uuid}`);
  const actions = (h: Host) => hostActions(h, open);
  const [search, setSearch] = useState("");
  const [quick, setQuick] = useState<QuickFilter>("all");
  const [filters, setFilters] = useState<FilterValues>({});
  const live = useLiveHosts();
  const prefix = `wwc.${me.user.username}.hosts`;
  const [columns, setColumns] = usePersistentState<string[]>(`${prefix}.columns`, DEFAULT_COLUMNS,
    (v) => Array.isArray(v) && v.length > 0 && v.every((id) => id in COLUMN_BY_ID));
  const [sort, setSort] = usePersistentState<SortState>(`${prefix}.sort`, DEFAULT_SORT,
    (v) => typeof v === "object" && v !== null && v.column in COLUMN_BY_ID);

  const { data, error, isLoading, isFetching } = useQuery({
    queryKey: ["hosts"],
    queryFn: () => api.get<HostsAnswer>("/api/hosts"),
    refetchInterval: live === "live" ? false : 30_000,     // polling only while the live channel is down
  });
  const refresh = async () => {
    const fresh = await api.get<HostsAnswer>("/api/hosts?refresh=true");
    queryClient.setQueryData(["hosts"], fresh);
  };

  const all = data?.hosts ?? [];
  const counts = Object.fromEntries(QUICK_FILTERS.map((f) => [f.id, all.filter(f.test).length]));
  const hosts = useMemo(() => {
    const test = QUICK_FILTERS.find((f) => f.id === quick)!.test;
    const q = search.trim().toLowerCase();
    const matches = (h: Host) =>
      !q || SEARCHED.some((k) => String(h[k] ?? "").toLowerCase().includes(q)) || h.ips.some((ip) => ip.includes(q));
    return sortHosts(all.filter((h) => test(h) && matchesFilters(h, filters) && matches(h)), sort);
  }, [all, quick, filters, search, sort]);

  const clickHeader = (id: string) =>
    setSort(sort.column === id ? { column: id, desc: !sort.desc }
      : { column: id, desc: COLUMN_BY_ID[id].sort !== "text" });   // numbers, dates: largest first
  const more = (h: Host) => (
    <ActionIcon variant="subtle" color="gray" size="lg" aria-label="Actions"
                onClick={(e) => openFrom(e, h.name, actions(h))}>
      <IconDotsVertical size={18} />
    </ActionIcon>
  );

  return (
    <Stack gap="md">
      <Group justify="space-between" wrap="nowrap">
        <Stack gap={0} style={{ minWidth: 0 }}>
          <Title order={2}>Machines</Title>
          <Text size="xs" c="dimmed" truncate>{data?.server ?? me.wapt_url}</Text>
        </Stack>
        <Group gap="xs" wrap="nowrap">
          {live === "live" ? (
            <Tooltip label="État des machines mis à jour automatiquement">
              <Badge variant="dot" color="green" size="lg" tt="none">En direct</Badge>
            </Tooltip>
          ) : data && (
            <Text size="xs" c="dimmed" visibleFrom="sm">
              lu <RelativeDate iso={new Date(data.read_at * 1000).toISOString()} />
            </Text>
          )}
          <Tooltip label="Relire l'inventaire sur le serveur WAPT">
            <ActionIcon variant="default" size="lg" onClick={refresh} loading={isFetching} aria-label="Actualiser">
              <IconRefresh size={18} />
            </ActionIcon>
          </Tooltip>
        </Group>
      </Group>

      <SimpleGrid cols={4} spacing="xs">
        {QUICK_FILTERS.map((f) => (
          <Indicator key={f.id} label={f.label} value={counts[f.id] ?? 0} color={f.color} active={quick === f.id}
                     compact={!!phone} onClick={() => setQuick(quick === f.id ? "all" : f.id)} />
        ))}
      </SimpleGrid>

      {phone ? (
        <Stack gap="xs">
          <TextInput placeholder="Nom, utilisateur, IP, OS…" leftSection={<IconSearch size={16} />} size="md"
                     value={search} onChange={(e) => setSearch(e.currentTarget.value)} />
          <Group gap="xs" wrap="nowrap">
            <Select data={COLUMNS.map((c) => ({ value: c.id, label: c.label }))} value={sort.column} size="md"
                    onChange={(v) => v && setSort({ column: v, desc: sort.desc })} allowDeselect={false}
                    aria-label="Trier par" leftSection={<Text size="xs" c="dimmed">Tri</Text>} leftSectionWidth={40}
                    style={{ flex: 1 }} />
            <ActionIcon variant="default" size="input-md" onClick={() => setSort({ ...sort, desc: !sort.desc })}
                        aria-label="Inverser le tri">
              {sort.desc ? <IconSortDescending size={20} /> : <IconSortAscending size={20} />}
            </ActionIcon>
            <Filters hosts={all} filters={filters} onChange={setFilters} />
          </Group>
        </Stack>
      ) : (
        <Group gap="xs" wrap="nowrap">
          <TextInput placeholder="Rechercher : nom, utilisateur, IP, OS, n° de série…" style={{ flex: 1 }}
                     leftSection={<IconSearch size={16} />} value={search}
                     onChange={(e) => setSearch(e.currentTarget.value)} />
          <Filters hosts={all} filters={filters} onChange={setFilters} />
          <ColumnsPicker visible={columns} onChange={setColumns} />
        </Group>
      )}
      <ActiveFilters filters={filters} onChange={setFilters} />

      {isLoading && <Loader />}
      {error && <Alert color="red" title="Inventaire indisponible">{(error as Error).message}</Alert>}
      {data && !hosts.length && <Text c="dimmed">Aucune machine ne correspond.</Text>}

      {phone ? (
        <Stack gap="xs">
          {hosts.map((h) => (
            <Card key={h.uuid} withBorder padding="sm" radius="md" {...bind(h.name, actions(h))}
                  onClick={() => open(h.uuid)}
                  style={{ userSelect: "none", WebkitTouchCallout: "none", cursor: "pointer" }}>
              <Group justify="space-between" wrap="nowrap" align="flex-start">
                <Stack gap={4} style={{ minWidth: 0 }}>
                  <Text fw={600} truncate>{h.name}</Text>
                  <Text size="sm" c="dimmed" truncate>
                    {[h.os_name, h.os_release].filter(Boolean).join(" · ")}
                  </Text>
                  {(h.last_user || h.main_ip) && (
                    <Text size="sm" c="dimmed" truncate>{[h.last_user, h.main_ip].filter(Boolean).join(" · ")}</Text>
                  )}
                  <Group gap={6}>
                    <ConnectedBadge connected={h.connected} />
                    <StatusBadge value={h.status} />
                  </Group>
                </Stack>
                {more(h)}
              </Group>
            </Card>
          ))}
        </Stack>
      ) : (
        <ScrollArea type="auto">
          <Table highlightOnHover stickyHeader verticalSpacing={6} fz="sm">
            <Table.Thead>
              <Table.Tr>
                {columns.map((id) => (
                  <Table.Th key={id} style={{ whiteSpace: "nowrap", cursor: "pointer", userSelect: "none" }}
                            onClick={() => clickHeader(id)}
                            aria-sort={sort.column === id ? (sort.desc ? "descending" : "ascending") : "none"}>
                    <Group gap={4} wrap="nowrap">
                      {COLUMN_BY_ID[id].label}
                      <SortIcon column={id} sort={sort} />
                    </Group>
                  </Table.Th>
                ))}
                <Table.Th w={48} />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {hosts.map((h) => (
                <Table.Tr key={h.uuid} {...bind(h.name, actions(h))} onClick={() => open(h.uuid)}
                          style={{ cursor: "pointer" }}
                          bg={h.uuid === selected ? "var(--mantine-color-blue-light)" : undefined}>
                  {columns.map((id) => (
                    <Table.Td key={id} style={COLUMN_BY_ID[id].nowrap ? { whiteSpace: "nowrap" } : undefined}>
                      <Cell column={COLUMN_BY_ID[id]} host={h} />
                    </Table.Td>
                  ))}
                  <Table.Td>{more(h)}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      )}
      <HostDetail uuid={selected} onClose={() => navigate("/")} />
    </Stack>
  );
}
