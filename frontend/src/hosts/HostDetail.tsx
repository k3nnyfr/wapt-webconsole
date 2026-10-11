// Host detail: side panel on a computer, full screen on a phone. Each tab loads its data when first opened.

import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Code,
  Drawer,
  Group,
  Loader,
  Modal,
  Progress,
  ScrollArea,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { IconDotsVertical, IconLock, IconSearch } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useMemo, useState } from "react";

import { type AgentTask, type AgentTasks, ApiError, type HostDetail as Detail, type HostPackage, type Me,
  type Software, api, roleAtLeast } from "../api";
import { useActionMenu } from "../components/ActionMenu";
import { rfc3339, rfc3339Date } from "../dates";
import { type Target, useHostMenu, usePackageMenu } from "../ops/actions";
import { useAssign } from "../ops/assign";
import { useSigning } from "../ops/signing";
import { ConnectedBadge, RelativeDate, StatusBadge } from "./columns";

function Field({ label, children }: { label: string; children: ReactNode }) {
  if (children === "" || children === null || children === undefined) return null;
  return (
    <Group gap="xs" wrap="nowrap" align="flex-start">
      <Text size="sm" c="dimmed" w={150} style={{ flexShrink: 0 }}>{label}</Text>
      <Text size="sm" style={{ wordBreak: "break-word" }} component="div">{children}</Text>
    </Group>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card withBorder radius="md" padding="sm">
      <Text fw={600} mb="xs">{title}</Text>
      <Stack gap={6}>{children}</Stack>
    </Card>
  );
}

const date = (iso: string) => (iso ? <RelativeDate iso={iso} /> : "");

function Summary({ d }: { d: Detail }) {
  const h = d.host;
  return (
    <SimpleGrid cols={{ base: 1, md: 2 }} spacing="sm">
      <Section title="Système">
        <Field label="Système">{h.os_name}</Field>
        <Field label="Édition">{h.os_release}</Field>
        <Field label="Version">{h.os_version}</Field>
        <Field label="Architecture">{h.os_architecture}</Field>
        <Field label="Installé le">{rfc3339(d.hardware.os_installed_on)}</Field>
        <Field label="Dernier démarrage">{date(h.last_boot)}</Field>
      </Section>
      <Section title="WAPT">
        <Field label="Connexion"><ConnectedBadge connected={h.connected} /></Field>
        <Field label="État"><StatusBadge value={h.status} /></Field>
        <Field label="Audit"><StatusBadge value={h.audit_status} /></Field>
        <Field label="Mises à jour">{String(h.pending)}</Field>
        <Field label="Erreurs">{String(h.errors)}</Field>
        <Field label="Dernière remontée">{date(h.last_seen)}</Field>
        <Field label="Agent">{h.wapt_version}</Field>
        <Field label="UUID"><Code>{h.uuid}</Code></Field>
      </Section>
      <Section title="Réseau">
        <Field label="Adresse IP">{h.main_ip}</Field>
        <Field label="Adresses IP">{h.ips.join(", ")}</Field>
        <Field label="Adresse MAC">{h.mac}</Field>
        <Field label="Domaine">{h.dnsdomain}</Field>
        <Field label="Passerelles">{d.hardware.gateways.join(", ")}</Field>
      </Section>
      <Section title="Utilisateurs">
        <Field label="Dernier utilisateur">{h.last_user}</Field>
        <Field label="Sessions ouvertes">{h.users.join(", ") || "aucune"}</Field>
        <Field label="Description">{h.description}</Field>
      </Section>
      <Section title="Matériel">
        <Field label="Fabricant">{h.manufacturer}</Field>
        <Field label="Modèle">{h.model}</Field>
        <Field label="N° de série">{h.serial}</Field>
        <Field label="BIOS">{[d.hardware.bios_vendor, d.hardware.bios_version, d.hardware.bios_date]
          .filter(Boolean).join(" · ")}</Field>
        <Field label="Processeur">{h.cpu}</Field>
        <Field label="Mémoire">{h.memory_gb == null ? "" : `${h.memory_gb} Go`}</Field>
      </Section>
      {d.hardware.drives.length > 0 && (
        <Section title="Disques">
          {d.hardware.drives.map((drive) => {
            const used = drive.free_percent == null ? null : 100 - drive.free_percent;
            return (
              <Stack key={drive.name} gap={2}>
                <Group justify="space-between">
                  <Text size="sm">{drive.name} {drive.filesystem}</Text>
                  <Text size="sm" c="dimmed">{drive.free_gb} Go libres / {drive.size_gb} Go</Text>
                </Group>
                {used != null && <Progress value={used} color={used > 90 ? "red" : used > 80 ? "orange" : "blue"} />}
              </Stack>
            );
          })}
        </Section>
      )}
    </SimpleGrid>
  );
}

function PackageLog({ pkg, onClose }: { pkg: HostPackage | null; onClose: () => void }) {
  const phone = useMediaQuery("(max-width: 48em)");
  return (
    <Modal opened={pkg !== null} onClose={onClose} title={pkg?.package} size="xl" fullScreen={!!phone}>
      {pkg && (
        <Stack>
          <Group gap="xs">
            <StatusBadge value={pkg.install_status} />
            <Text size="sm">{pkg.version}</Text>
            {pkg.install_date && <Text size="sm" c="dimmed">installé {date(pkg.install_date)}</Text>}
          </Group>
          {pkg.description && <Text size="sm">{pkg.description}</Text>}
          <Text fw={600} size="sm">Journal d'installation</Text>
          <Code block style={{ maxHeight: "40vh", overflow: "auto", whiteSpace: "pre-wrap" }}>
            {pkg.install_output || "(vide)"}
          </Code>
          {(pkg.audit_status || pkg.audit_output) && (
            <>
              <Group gap="xs">
                <Text fw={600} size="sm">Audit</Text>
                <StatusBadge value={pkg.audit_status} />
                {pkg.audit_on && <Text size="sm" c="dimmed">{date(pkg.audit_on)}</Text>}
              </Group>
              <Code block style={{ maxHeight: "30vh", overflow: "auto", whiteSpace: "pre-wrap" }}>
                {pkg.audit_output || "(vide)"}
              </Code>
            </>
          )}
        </Stack>
      )}
    </Modal>
  );
}

function Packages({ uuid, me, host }: { uuid: string; me: Me; host: Target }) {
  const packageMenu = usePackageMenu(me);
  const { openFrom } = useActionMenu();
  const [problems, setProblems] = useState(false);
  const [search, setSearch] = useState("");
  const [log, setLog] = useState<HostPackage | null>(null);
  const { data, error, isLoading } = useQuery({
    queryKey: ["host-packages", uuid],
    queryFn: () => api.get<HostPackage[]>(`/api/hosts/${uuid}/packages`),
  });
  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (data ?? []).filter((p) =>
      (!problems || p.install_status !== "OK" || (p.audit_status && p.audit_status !== "OK")) &&
      (!q || p.package.toLowerCase().includes(q) || p.name.toLowerCase().includes(q)));
  }, [data, problems, search]);
  if (isLoading) return <Loader />;
  if (error) return <Alert color="red">{(error as Error).message}</Alert>;

  return (
    <Stack gap="sm">
      <Group gap="sm">
        <TextInput placeholder="Filtrer les paquets" leftSection={<IconSearch size={16} />} style={{ flex: 1 }}
                   value={search} onChange={(e) => setSearch(e.currentTarget.value)} />
        <Switch label="Problèmes seulement" checked={problems} onChange={(e) => setProblems(e.currentTarget.checked)} />
      </Group>
      <Text size="xs" c="dimmed">{shown.length} / {data?.length} paquets · toucher un paquet pour ses journaux</Text>
      <Stack gap={4}>
        {shown.map((p, i) => (
          // WAPT may report the same package twice (to install and to upgrade): the index keeps keys unique
          <UnstyledButton key={`${p.package}-${p.version}-${i}`} onClick={() => setLog(p)}>
            <Card withBorder radius="sm" padding="xs">
              <Group justify="space-between" wrap="nowrap" gap="xs">
                <Stack gap={0} style={{ minWidth: 0 }}>
                  <Text size="sm" fw={500} truncate>{p.name || p.package}</Text>
                  <Text size="xs" c="dimmed" truncate>
                    {[p.package, p.version, p.section === "group" ? "groupe" : p.section === "host" ? "paquet machine" : ""]
                      .filter(Boolean).join(" · ")}
                  </Text>
                </Stack>
                <Group gap={4} wrap="nowrap">
                  {p.audit_status && p.audit_status !== "OK" && <StatusBadge value={p.audit_status} />}
                  <StatusBadge value={p.install_status} />
                  {p.section !== "host" && packageMenu(host, p.package).length > 0 && (
                    <ActionIcon component="div" variant="subtle" color="gray" aria-label="Actions sur le paquet"
                                onClick={(e) => openFrom(e, p.package, packageMenu(host, p.package))}>
                      <IconDotsVertical size={16} />
                    </ActionIcon>
                  )}
                </Group>
              </Group>
            </Card>
          </UnstyledButton>
        ))}
      </Stack>
      <PackageLog pkg={log} onClose={() => setLog(null)} />
    </Stack>
  );
}

function Softwares({ uuid }: { uuid: string }) {
  const phone = useMediaQuery("(max-width: 48em)");
  const [hideSystem, setHideSystem] = useState(true);
  const [search, setSearch] = useState("");
  const { data, error, isLoading } = useQuery({
    queryKey: ["host-softwares", uuid],
    queryFn: () => api.get<Software[]>(`/api/hosts/${uuid}/softwares`),
  });
  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (data ?? []).filter((s) => (!hideSystem || !s.system_component) &&
      (!q || s.name.toLowerCase().includes(q) || s.publisher.toLowerCase().includes(q)));
  }, [data, hideSystem, search]);
  if (isLoading) return <Loader />;
  if (error) return <Alert color="red">{(error as Error).message}</Alert>;

  return (
    <Stack gap="sm">
      <Group gap="sm">
        <TextInput placeholder="Filtrer : nom, éditeur" leftSection={<IconSearch size={16} />} style={{ flex: 1 }}
                   value={search} onChange={(e) => setSearch(e.currentTarget.value)} />
        <Switch label="Masquer les composants système" checked={hideSystem}
                onChange={(e) => setHideSystem(e.currentTarget.checked)} />
      </Group>
      <Text size="xs" c="dimmed">{shown.length} / {data?.length} logiciels</Text>
      {phone ? (
        <Stack gap={6}>
          {shown.map((s) => (
            <div key={s.key + s.name}>
              <Text size="sm" fw={500}>{s.name}</Text>
              <Text size="xs" c="dimmed">{[s.version, s.publisher].filter(Boolean).join(" · ")}</Text>
            </div>
          ))}
        </Stack>
      ) : (
        <Table striped fz="sm" verticalSpacing={4}>
          <Table.Thead>
            <Table.Tr><Table.Th>Nom</Table.Th><Table.Th>Version</Table.Th><Table.Th>Éditeur</Table.Th>
              <Table.Th>Installé le</Table.Th></Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {shown.map((s) => (
              <Table.Tr key={s.key + s.name}>
                <Table.Td>{s.name}</Table.Td><Table.Td>{s.version}</Table.Td><Table.Td>{s.publisher}</Table.Td>
                <Table.Td style={{ whiteSpace: "nowrap" }}>{rfc3339Date(s.install_date)}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}

const RUNSTATUS: Record<string, string> = { DONE: "green", ERROR: "red", CANCELLED: "gray", RUNNING: "blue" };

function TaskRow({ t, onClick }: { t: AgentTask; onClick: () => void }) {
  return (
    <UnstyledButton onClick={onClick}>
      <Card withBorder radius="sm" padding="xs">
        <Stack gap={4}>
          <Group justify="space-between" wrap="nowrap">
            <Text size="sm" fw={500} truncate>{t.description}</Text>
            {t.runstatus && <Badge size="sm" variant="light" color={RUNSTATUS[t.runstatus] ?? "gray"}>{t.runstatus}</Badge>}
          </Group>
          {t.summary && <Text size="xs" c="dimmed" lineClamp={2}>{t.summary}</Text>}
          {t.progress != null && t.runstatus === "RUNNING" && <Progress value={t.progress} size="sm" animated />}
          <Text size="xs" c="dimmed">
            {[t.created_by && `par ${t.created_by}`, t.finished && `terminée ${rfc3339(t.finished)}`]
              .filter(Boolean).join(" · ")}
          </Text>
        </Stack>
      </Card>
    </UnstyledButton>
  );
}

function Tasks({ uuid, connected }: { uuid: string; connected: boolean }) {
  const { status, ensureUnlocked } = useSigning();
  const [log, setLog] = useState<AgentTask | null>(null);
  const unlocked = !!status?.unlocked;
  const { data, error, isLoading } = useQuery({
    queryKey: ["host-tasks", uuid],
    queryFn: () => api.get<AgentTasks>(`/api/hosts/${uuid}/tasks`),
    enabled: unlocked && connected,
    refetchInterval: 3000,
    retry: false,
  });
  if (!connected) return <Alert color="gray">Machine déconnectée : ses tâches ne sont pas consultables.</Alert>;
  if (!unlocked) {
    return (
      <Alert color="blue" title="Clé de signature verrouillée">
        <Stack gap="xs" align="flex-start">
          <Text size="sm">L'agent n'accepte que des demandes signées, même pour consulter ses tâches.</Text>
          <Button size="xs" leftSection={<IconLock size={14} />} onClick={() => void ensureUnlocked()}>Déverrouiller</Button>
        </Stack>
      </Alert>
    );
  }
  if (isLoading) return <Loader />;
  if (error) return <Alert color="red">{error instanceof ApiError ? error.message : String(error)}</Alert>;
  if (!data) return null;
  const section = (title: string, tasks: AgentTask[]) => tasks.length > 0 && (
    <Stack gap={4}>
      <Text fw={600} size="sm">{title} ({tasks.length})</Text>
      {tasks.map((t) => <TaskRow key={`${title}-${t.id}`} t={t} onClick={() => setLog(t)} />)}
    </Stack>
  );
  return (
    <Stack gap="md">
      <Text size="xs" c="dimmed">Actualisé toutes les 3 secondes · toucher une tâche pour son journal</Text>
      {section("En cours", data.running ? [data.running] : [])}
      {section("En attente", data.pending)}
      {section("En erreur", data.errors)}
      {section("Terminées", data.done)}
      {!data.running && !data.pending.length && !data.done.length && !data.errors.length &&
        <Text size="sm" c="dimmed">Aucune tâche récente.</Text>}
      <Modal opened={log !== null} onClose={() => setLog(null)} title={log?.description} size="xl">
        <Code block style={{ maxHeight: "60vh", overflow: "auto", whiteSpace: "pre-wrap" }}>{log?.logs || "(vide)"}</Code>
      </Modal>
    </Stack>
  );
}

function HostPackageTab({ d, me }: { d: Detail; me: Me }) {
  const assign = useAssign();
  const hp = d.host_package;
  const edit = roleAtLeast(me.user.role, "admin") && (
    <Button size="xs" variant="light" style={{ alignSelf: "flex-start" }}
            onClick={() => assign({ hosts: [{ uuid: d.host.uuid, name: d.host.name }] })}>
      {hp ? "Modifier les paquets et groupes…" : "Créer le paquet machine…"}
    </Button>
  );
  if (!hp) return <Stack><Alert color="gray">Aucun paquet machine sur le serveur pour cette machine.</Alert>{edit}</Stack>;
  return (
    <Stack gap="sm">
      {edit}
      <Group gap="lg">
        <Field label="Version">{hp.version}</Field>
        <Field label="Signé par">{hp.signer}</Field>
        <Field label="Signé">{date(hp.signature_date)}</Field>
      </Group>
      <Text fw={600} size="sm">Dépendances ({hp.depends.length})</Text>
      <Group gap={6}>{hp.depends.map((p) => <Badge key={p} variant="light" tt="none">{p}</Badge>)}</Group>
      <Text fw={600} size="sm">Conflits ({hp.conflicts.length})</Text>
      {hp.conflicts.length
        ? <Group gap={6}>{hp.conflicts.map((p) => <Badge key={p} color="red" variant="light" tt="none">{p}</Badge>)}</Group>
        : <Text size="sm" c="dimmed">aucun</Text>}
    </Stack>
  );
}

export default function HostDetail({ uuid, me, onClose }: { uuid: string | undefined; me: Me; onClose: () => void }) {
  const phone = useMediaQuery("(max-width: 48em)");
  const hostMenu = useHostMenu(me);
  const { openFrom } = useActionMenu();
  const operator = roleAtLeast(me.user.role, "operator");
  const [tab, setTab] = useState<string | null>("summary");
  const { data, error, isLoading } = useQuery({
    queryKey: ["host", uuid],
    queryFn: () => api.get<Detail>(`/api/hosts/${uuid}`),
    enabled: !!uuid,
  });

  return (
    <Drawer opened={!!uuid} onClose={onClose} position="right" size={phone ? "100%" : "min(960px, 75%)"}
            padding="md" scrollAreaComponent={ScrollArea.Autosize}
            title={<Stack gap={2}>
              <Title order={3}>{data?.host.name ?? "Machine"}</Title>
              {data && <Group gap={6}><ConnectedBadge connected={data.host.connected} />
                <StatusBadge value={data.host.status} />
                {operator && (
                  <Button size="compact-xs" variant="light" leftSection={<IconDotsVertical size={12} />}
                          onClick={(e) => openFrom(e, data.host.name, hostMenu([data.host]))}>Actions</Button>
                )}</Group>}
            </Stack>}>
      {isLoading && <Loader />}
      {error && <Alert color="red" title="Fiche indisponible">{(error as Error).message}</Alert>}
      {data && uuid && (
        <Tabs value={tab} onChange={setTab} keepMounted={false} style={{ minWidth: 0 }}>
          {/* on a phone the tabs scroll sideways instead of widening the panel */}
          <Tabs.List mb="md" style={phone ? { flexWrap: "nowrap", overflowX: "auto", maxWidth: "calc(100vw - 32px)",
                                               scrollbarWidth: "none" } : undefined}>
            <Tabs.Tab value="summary">Résumé</Tabs.Tab>
            <Tabs.Tab value="packages">Paquets</Tabs.Tab>
            <Tabs.Tab value="softwares">Logiciels</Tabs.Tab>
            {operator && <Tabs.Tab value="tasks">Tâches</Tabs.Tab>}
            <Tabs.Tab value="host-package">Paquet machine</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="summary"><Summary d={data} /></Tabs.Panel>
          <Tabs.Panel value="packages">
            <Packages uuid={uuid} me={me}
                      host={{ uuid, name: data.host.name, connected: data.host.connected }} />
          </Tabs.Panel>
          {operator && <Tabs.Panel value="tasks"><Tasks uuid={uuid} connected={data.host.connected} /></Tabs.Panel>}
          <Tabs.Panel value="softwares"><Softwares uuid={uuid} /></Tabs.Panel>
          <Tabs.Panel value="host-package"><HostPackageTab d={data} me={me} /></Tabs.Panel>
        </Tabs>
      )}
    </Drawer>
  );
}
