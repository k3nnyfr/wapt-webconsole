// Tranquil IT store: available updates of the repository packages, catalogue to import from, import jobs.

import { ActionIcon, Alert, Anchor, Badge, Button, Card, Checkbox, Group, Loader, Modal, Paper, ScrollArea,
  SegmentedControl, Select, Stack, Switch, Table, Tabs, Text, TextInput, Title, Tooltip } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { IconDownload, IconRefresh, IconSearch } from "@tabler/icons-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { type Job, type Me, type StoreCatalogue, type StoreRow, api, roleAtLeast } from "../api";
import { rfc3339 } from "../dates";
import { RelativeDate } from "../hosts/columns";
import { PackageIcon, formatSize } from "../repo/common";
import ImportDialog, { JobProgress } from "./ImportDialog";

const SHOWN = 200;
const STATES: Record<StoreRow["state"], { label: string; color: string }> = {
  absent: { label: "absent du dépôt", color: "gray" },
  ok: { label: "dans le dépôt", color: "green" },
  update: { label: "mise à jour", color: "orange" },
};

function StateBadge({ row }: { row: StoreRow }) {
  return (
    <Group gap={4} wrap="nowrap">
      <Badge size="sm" variant="light" color={STATES[row.state].color}>{STATES[row.state].label}</Badge>
      {row.restricted && <Badge size="sm" variant="outline" color="grape">Enterprise</Badge>}
    </Group>
  );
}

function StoreDetail({ row, onClose, onImport }: { row: StoreRow; onClose: () => void; onImport?: () => void }) {
  return (
    <Modal opened onClose={onClose} size="lg" title={
      <Group gap="sm" wrap="nowrap"><PackageIcon icon={row.icon} store size={36} />
        <Stack gap={0}><Title order={4}>{row.title || row.name}</Title>
          <Text size="xs" c="dimmed">{row.store_package} · {row.version}</Text></Stack></Group>}>
      <Stack>
        {row.description && <Text size="sm" style={{ whiteSpace: "pre-line" }}>{row.description}</Text>}
        <Group gap="xs"><StateBadge row={row} />{row.categories.map((c) => <Badge key={c} size="sm" variant="default"
                                                                                    tt="none">{c}</Badge>)}</Group>
        <Text size="sm" c="dimmed">{[row.editor, row.licence].filter(Boolean).join(" · ")}</Text>
        {row.homepage && <Anchor href={row.homepage} target="_blank" rel="noopener noreferrer" size="sm">{row.homepage}</Anchor>}
        <Table fz="sm" verticalSpacing={4}>
          <Table.Thead><Table.Tr><Table.Th>Cible</Table.Th><Table.Th>Store</Table.Th><Table.Th>Dépôt</Table.Th>
            <Table.Th>Taille</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {row.targets.map((t) => (
              <Table.Tr key={t.target}>
                <Table.Td>{t.target}</Table.Td><Table.Td>{t.version}</Table.Td>
                <Table.Td c={t.state === "update" ? "orange" : undefined}>{t.repo_version ?? "—"}</Table.Td>
                <Table.Td>{formatSize(t.size)}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        <Text size="xs" c="dimmed">Signé par Tranquil IT, {rfc3339(row.signature_date)}</Text>
        {onImport && !row.restricted && row.state !== "ok" && (
          <Group justify="flex-end"><Button leftSection={<IconDownload size={16} />} onClick={onImport}>
            {row.state === "update" ? "Mettre à jour" : "Importer"}</Button></Group>
        )}
      </Stack>
    </Modal>
  );
}

function Rows({ rows, admin, checked, toggle, open }: {
  rows: StoreRow[]; admin: boolean; checked: Set<string>; toggle: (name: string) => void; open: (r: StoreRow) => void;
}) {
  const phone = useMediaQuery("(max-width: 48em)");
  const selectable = (r: StoreRow) => admin && !r.restricted && r.state !== "ok";
  if (phone) {
    return (
      <Stack gap="xs">
        {rows.map((r) => (
          <Card key={r.name} withBorder padding="sm" radius="md" onClick={() => open(r)} style={{ cursor: "pointer" }}>
            <Group wrap="nowrap" align="flex-start">
              {selectable(r) && <Checkbox checked={checked.has(r.name)} onClick={(e) => e.stopPropagation()}
                                          onChange={() => toggle(r.name)} mt={8} aria-label="Sélection" />}
              <PackageIcon icon={r.icon} store size={36} />
              <Stack gap={4} style={{ minWidth: 0, flex: 1 }}>
                <Text fw={600} truncate>{r.title || r.name}</Text>
                <Text size="xs" c="dimmed" truncate>{r.name} · {r.version}</Text>
                <StateBadge row={r} />
              </Stack>
            </Group>
          </Card>
        ))}
      </Stack>
    );
  }
  return (
    <ScrollArea type="auto">
      <Table highlightOnHover stickyHeader fz="sm" verticalSpacing={6}>
        <Table.Thead>
          <Table.Tr>
            {admin && <Table.Th w={36} />}
            <Table.Th>Paquet</Table.Th><Table.Th>Version</Table.Th><Table.Th>Dépôt</Table.Th>
            <Table.Th>Catégories</Table.Th><Table.Th>État</Table.Th><Table.Th>Taille</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((r) => (
            <Table.Tr key={r.name} onClick={() => open(r)} style={{ cursor: "pointer" }}
                      bg={checked.has(r.name) ? "var(--mantine-color-blue-light)" : undefined}>
              {admin && (
                <Table.Td onClick={(e) => e.stopPropagation()}>
                  {selectable(r) && <Checkbox checked={checked.has(r.name)} onChange={() => toggle(r.name)}
                                              aria-label={`Sélectionner ${r.name}`} />}
                </Table.Td>
              )}
              <Table.Td>
                <Group gap="sm" wrap="nowrap">
                  <PackageIcon icon={r.icon} store />
                  <Stack gap={0} style={{ minWidth: 0 }}>
                    <Text size="sm" fw={500} truncate>{r.title || r.name}</Text>
                    <Text size="xs" c="dimmed" truncate>{r.name}</Text>
                  </Stack>
                </Group>
              </Table.Td>
              <Table.Td style={{ whiteSpace: "nowrap" }}>{r.version}</Table.Td>
              <Table.Td style={{ whiteSpace: "nowrap" }}>
                {[...new Set(r.targets.map((t) => t.repo_version).filter(Boolean))].join(", ") || "—"}
              </Table.Td>
              <Table.Td><Text size="xs" c="dimmed" lineClamp={1}>{r.categories.join(", ")}</Text></Table.Td>
              <Table.Td><StateBadge row={r} /></Table.Td>
              <Table.Td style={{ whiteSpace: "nowrap" }}>{formatSize(r.size)}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </ScrollArea>
  );
}

function JobsList() {
  const [open, setOpen] = useState<string | null>(null);
  const { data, isLoading } = useQuery({ queryKey: ["jobs"], queryFn: () => api.get<Job[]>("/api/jobs"),
    refetchInterval: 3000 });
  if (isLoading) return <Loader />;
  if (!data?.length) return <Text c="dimmed" size="sm">Aucun import depuis le démarrage de la console.</Text>;
  return (
    <Stack gap="xs">
      {data.map((j) => (
        <Card key={j.id} withBorder padding="sm" radius="md" onClick={() => setOpen(j.id)} style={{ cursor: "pointer" }}>
          <Group justify="space-between" wrap="nowrap">
            <Stack gap={0} style={{ minWidth: 0 }}>
              <Text size="sm" fw={500} truncate>{[...new Set(j.items.map((i) => i.name))].join(", ")}</Text>
              <Text size="xs" c="dimmed">{rfc3339(j.created)} · {j.user} · {j.message || "en cours"}</Text>
            </Stack>
            <Badge variant="light" color={j.status === "done" ? "green" : j.status === "failed" ? "red" : "blue"}>
              {j.status === "running" ? "en cours" : j.status === "done" ? "terminé" : "erreurs"}
            </Badge>
          </Group>
        </Card>
      ))}
      {open && <Modal opened onClose={() => setOpen(null)} title="Import" size="lg"><JobProgress jobId={open} /></Modal>}
    </Stack>
  );
}

export default function StorePage({ me }: { me: Me }) {
  const phone = useMediaQuery("(max-width: 48em)");
  const queryClient = useQueryClient();
  const admin = roleAtLeast(me.user.role, "admin");
  const [tab, setTab] = useState<string | null>("updates");
  const [search, setSearch] = useState("");
  const [state, setState] = useState("all");
  const [category, setCategory] = useState<string | null>(null);
  const [showRestricted, setShowRestricted] = useState(false);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [detail, setDetail] = useState<StoreRow | null>(null);
  const [importing, setImporting] = useState<string[] | null>(null);
  const { data, error, isLoading, isFetching } = useQuery({
    queryKey: ["store"], queryFn: () => api.get<StoreCatalogue>("/api/store"), staleTime: 300_000,
  });
  const refresh = async () => queryClient.setQueryData(["store"], await api.get<StoreCatalogue>("/api/store?refresh=true"));

  const rows = data?.rows ?? [];
  const updates = rows.filter((r) => r.state === "update");
  const categories = useMemo(() => [...new Set(rows.flatMap((r) => r.categories))].sort(), [rows]);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter((r) => (showRestricted || !r.restricted) && (state === "all" || r.state === state)
      && (!category || r.categories.includes(category))
      && (!q || [r.name, r.title, r.description, r.editor].some((v) => v.toLowerCase().includes(q))));
  }, [rows, search, state, category, showRestricted]);
  const toggle = (name: string) => {
    const next = new Set(checked);
    if (!next.delete(name)) next.add(name);
    setChecked(next);
  };

  return (
    <Stack gap="md">
      <Group justify="space-between" wrap="nowrap">
        <Stack gap={0} style={{ minWidth: 0 }}>
          <Title order={2}>Store</Title>
          {data && <Text size="xs" c="dimmed" truncate>
            Tranquil IT · index {data.modified ? <RelativeDate iso={new Date(data.modified).toISOString()} /> : "—"}
            {" "}· importés en {data.prefix}-… · {data.fleet.join(", ")}
          </Text>}
        </Stack>
        <Tooltip label="Relire l'index du store">
          <ActionIcon variant="default" size="lg" onClick={refresh} loading={isFetching} aria-label="Actualiser">
            <IconRefresh size={18} />
          </ActionIcon>
        </Tooltip>
      </Group>
      {isLoading && <Group gap="xs"><Loader size="sm" /><Text size="sm" c="dimmed">Lecture de l'index du store (17 Mo la première fois)…</Text></Group>}
      {error && <Alert color="red" title="Store indisponible">{(error as Error).message}</Alert>}
      {data && !data.trusted && (
        <Alert color="red">Aucun certificat de confiance trouvé dans l'index : import impossible (WWC_STORE_TRUSTED_FINGERPRINTS).</Alert>
      )}

      {data && (
        <Tabs value={tab} onChange={setTab} keepMounted={false}>
          <Tabs.List mb="md">
            <Tabs.Tab value="updates" rightSection={updates.length ? <Badge size="xs" color="orange">{updates.length}</Badge> : null}>
              Mises à jour</Tabs.Tab>
            <Tabs.Tab value="catalogue">Catalogue</Tabs.Tab>
            {roleAtLeast(me.user.role, "operator") && <Tabs.Tab value="jobs">Imports</Tabs.Tab>}
          </Tabs.List>

          <Tabs.Panel value="updates">
            <Stack>
              {!updates.length && <Alert color="green">Les paquets du dépôt sont à jour par rapport au store.</Alert>}
              {updates.length > 0 && (
                <>
                  <Group justify="space-between">
                    <Text size="sm">{updates.length} paquet{updates.length > 1 ? "s" : ""} du dépôt ont une version plus
                      récente dans le store.</Text>
                    {admin && <Button leftSection={<IconDownload size={16} />}
                                      onClick={() => setImporting(updates.map((r) => r.name))}>Tout mettre à jour</Button>}
                  </Group>
                  <Rows rows={updates} admin={admin} checked={checked} toggle={toggle} open={setDetail} />
                </>
              )}
            </Stack>
          </Tabs.Panel>

          <Tabs.Panel value="catalogue">
            <Stack>
              <Group gap="xs" wrap={phone ? "wrap" : "nowrap"}>
                <TextInput placeholder="Rechercher : nom, éditeur, description" leftSection={<IconSearch size={16} />}
                           value={search} onChange={(e) => setSearch(e.currentTarget.value)} style={{ flex: 1, minWidth: 200 }} />
                <SegmentedControl value={state} onChange={setState} size={phone ? "xs" : "sm"}
                                  data={[{ value: "all", label: "Tous" }, { value: "absent", label: "Absents" },
                                         { value: "ok", label: "Dans le dépôt" }, { value: "update", label: "À mettre à jour" }]} />
                <Select placeholder="Catégorie" data={categories} value={category} onChange={setCategory} clearable
                        searchable w={phone ? "100%" : 200} />
              </Group>
              <Switch label="Montrer les paquets réservés à WAPT Enterprise" checked={showRestricted}
                      onChange={(e) => setShowRestricted(e.currentTarget.checked)} />
              <Text size="xs" c="dimmed">
                {filtered.length} paquet{filtered.length > 1 ? "s" : ""}
                {filtered.length > SHOWN && ` : ${SHOWN} premiers affichés, affinez la recherche`}
              </Text>
              <Rows rows={filtered.slice(0, SHOWN)} admin={admin} checked={checked} toggle={toggle} open={setDetail} />
            </Stack>
          </Tabs.Panel>

          <Tabs.Panel value="jobs"><JobsList /></Tabs.Panel>
        </Tabs>
      )}

      {checked.size > 0 && (
        <Paper withBorder shadow="md" radius="md" p="xs" pos="sticky" bottom={phone ? 72 : 12}>
          <Group justify="space-between" wrap="nowrap">
            <Text size="sm" fw={600}>{checked.size} sélectionné{checked.size > 1 ? "s" : ""}</Text>
            <Group gap="xs" wrap="nowrap">
              <Button size="xs" variant="default" onClick={() => setChecked(new Set())}>Désélectionner</Button>
              <Button size="xs" leftSection={<IconDownload size={14} />} onClick={() => setImporting([...checked])}>
                Importer…</Button>
            </Group>
          </Group>
        </Paper>
      )}
      {detail && <StoreDetail row={detail} onClose={() => setDetail(null)}
                              onImport={admin ? () => { setImporting([detail.name]); setDetail(null); } : undefined} />}
      {importing && <ImportDialog names={importing} onClose={() => { setImporting(null); setChecked(new Set()); }} />}
    </Stack>
  );
}
