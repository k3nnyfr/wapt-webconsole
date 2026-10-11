// Main page: inventory of the hosts, with indicators that act as quick filters, configurable and sortable columns,
// a table on a computer or tablet and cards on a phone.

import {
  ActionIcon,
  Affix,
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Group,
  Loader,
  Paper,
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
import {
  IconChevronDown,
  IconChevronUp,
  IconDotsVertical,
  IconRefresh,
  IconSearch,
  IconSelector,
  IconSortAscending,
  IconSortDescending,
} from "@tabler/icons-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useMatch, useNavigate } from "react-router";

import { type Host, type HostsAnswer, type Me, api, roleAtLeast } from "../api";
import { useActionMenu } from "../components/ActionMenu";
import { useLiveHosts } from "../live";
import { useHostMenu } from "../ops/actions";
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
  const hostMenu = useHostMenu(me);
  const actions = (h: Host) => hostMenu([h], open);
  const canAct = roleAtLeast(me.user.role, "operator");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [selectMode, setSelectMode] = useState(false);     // phone: tapping a card selects it instead of opening it
  const toggle = (uuid: string) => {
    const next = new Set(checked);
    if (!next.delete(uuid)) next.add(uuid);
    setChecked(next);
  };
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

  const checkedHosts = all.filter((h) => checked.has(h.uuid));
  const allShownChecked = hosts.length > 0 && hosts.every((h) => checked.has(h.uuid));
  const clearSelection = () => { setChecked(new Set()); setSelectMode(false); };
  const selectionBar = checkedHosts.length > 0 && (
    <Paper withBorder shadow="md" radius="md" p="xs">
      <Group justify="space-between" wrap="nowrap">
        <Text size="sm" fw={600}>{checkedHosts.length} sélectionnée{checkedHosts.length > 1 ? "s" : ""}</Text>
        <Group gap="xs" wrap="nowrap">
          <Button size="xs" variant="default" onClick={clearSelection}>Désélectionner</Button>
          <Button size="xs" leftSection={<IconDotsVertical size={14} />}
                  onClick={(e) => openFrom(e, `${checkedHosts.length} machines`, hostMenu(checkedHosts))}>
            Actions
          </Button>
        </Group>
      </Group>
    </Paper>
  );

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
          {canAct && (
            <Button variant={selectMode ? "light" : "default"} size="md"
                    onClick={() => (selectMode ? clearSelection() : setSelectMode(true))}>
              {selectMode ? "Terminer la sélection" : "Sélectionner des machines"}
            </Button>
          )}
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
      {!phone && selectionBar}
      {phone && selectionBar && <Affix position={{ bottom: 76, left: 12, right: 12 }}>{selectionBar}</Affix>}

      {phone ? (
        <Stack gap="xs">
          {hosts.map((h) => (
            <Card key={h.uuid} withBorder padding="sm" radius="md" {...bind(h.name, actions(h))}
                  onClick={() => (selectMode ? toggle(h.uuid) : open(h.uuid))}
                  bg={checked.has(h.uuid) ? "var(--mantine-color-blue-light)" : undefined}
                  style={{ userSelect: "none", WebkitTouchCallout: "none", cursor: "pointer" }}>
              <Group justify="space-between" wrap="nowrap" align="flex-start">
                {selectMode && <Checkbox checked={checked.has(h.uuid)} readOnly size="md" mt={2} aria-label="Sélection" />}
                <Stack gap={4} style={{ minWidth: 0, flex: 1 }}>
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
                {canAct && (
                  <Table.Th w={36}>
                    <Checkbox aria-label="Tout sélectionner" checked={allShownChecked}
                              indeterminate={!allShownChecked && hosts.some((h) => checked.has(h.uuid))}
                              onChange={() => setChecked(allShownChecked ? new Set()
                                : new Set([...checked, ...hosts.map((h) => h.uuid)]))} />
                  </Table.Th>
                )}
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
                          bg={h.uuid === selected || checked.has(h.uuid) ? "var(--mantine-color-blue-light)" : undefined}>
                  {canAct && (
                    <Table.Td onClick={(e) => e.stopPropagation()}>
                      <Checkbox aria-label={`Sélectionner ${h.name}`} checked={checked.has(h.uuid)}
                                onChange={() => toggle(h.uuid)} />
                    </Table.Td>
                  )}
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
      {phone && selectionBar && <div style={{ height: 64 }} />}
      <HostDetail uuid={selected} me={me} onClose={() => navigate("/")} />
    </Stack>
  );
}
