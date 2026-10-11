// Repository maintenance (admin): upload a signed package, clean superseded versions, delete a package or a version,
// remove hosts from the inventory.

import { Alert, Button, Checkbox, FileInput, Group, List, Loader, Modal, NumberInput, Progress, ScrollArea, Stack,
  Table, Text, TextInput } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconPackage } from "@tabler/icons-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, createContext, useCallback, useContext, useState } from "react";

import { ApiError, type CleanupCandidate, type PackageUsage, api, upload } from "../api";
import { formatSize } from "../repo/common";

const TYPE_COUNT_FROM = 10;

function useRefresh() {
  const queryClient = useQueryClient();
  return () => {
    for (const key of [["packages"], ["package"], ["journal"], ["hosts"], ["host"]]) {
      void queryClient.invalidateQueries({ queryKey: key });
    }
  };
}

export function UploadDialog({ onClose }: { onClose: () => void }) {
  const phone = useMediaQuery("(max-width: 48em)");
  const refresh = useRefresh();
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState("");
  const send = async () => {
    if (!file) return;
    setError("");
    setProgress(0);
    try {
      const info = await upload<{ package: string; version: string; signer: string }>("/api/packages/upload", file,
        setProgress);
      notifications.show({ color: "green", title: "Paquet envoyé",
        message: `${info.package} ${info.version}, signé par ${info.signer}` });
      refresh();
      onClose();
    } catch (e) {
      setError((e as Error).message);
      setProgress(null);
    }
  };
  return (
    <Modal opened onClose={onClose} title="Envoyer un paquet signé" fullScreen={!!phone} centered>
      <Stack>
        <Text size="sm">Paquet <b>.wapt</b> déjà signé (console WAPT, <code>wapt-get build-upload</code>…). Le serveur WAPT
          le refuse si son signataire n'est pas un certificat de confiance.</Text>
        <FileInput label="Fichier" accept=".wapt" value={file} onChange={setFile} clearable
                   leftSection={<IconPackage size={16} />} placeholder="Choisir un fichier .wapt" />
        {file && <Text size="xs" c="dimmed">{formatSize(file.size)}</Text>}
        {progress !== null && <Progress value={progress * 100} animated={progress < 1} />}
        {progress === 1 && !error && <Text size="xs" c="dimmed">Transmission au serveur WAPT…</Text>}
        {error && <Alert color="red">{error}</Alert>}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Annuler</Button>
          <Button onClick={send} disabled={!file} loading={progress !== null && !error}>Envoyer</Button>
        </Group>
      </Stack>
    </Modal>
  );
}

export function CleanupDialog({ onClose }: { onClose: () => void }) {
  const phone = useMediaQuery("(max-width: 48em)");
  const refresh = useRefresh();
  const [keep, setKeep] = useState(0);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const { data, isLoading } = useQuery({
    queryKey: ["cleanup", keep],
    queryFn: () => api.get<CleanupCandidate[]>(`/api/repository/cleanup?keep=${keep}`),
  });
  const chosen = (data ?? []).filter((c) => !excluded.has(c.package_uuid));
  const total = chosen.reduce((n, c) => n + c.size, 0);
  const toggle = (uuid: string) => {
    const next = new Set(excluded);
    if (!next.delete(uuid)) next.add(uuid);
    setExcluded(next);
  };
  const run = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await api.post<{ deleted: CleanupCandidate[]; skipped: number }>("/api/repository/cleanup",
        { package_uuids: chosen.map((c) => c.package_uuid), keep });
      notifications.show({ color: "green", title: "Dépôt nettoyé",
        message: `${r.deleted.length} version(s) supprimée(s)${r.skipped ? `, ${r.skipped} ignorée(s)` : ""}` });
      refresh();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal opened onClose={onClose} title="Nettoyer le dépôt" size="xl" fullScreen={!!phone}>
      <Stack>
        <Text size="sm">Versions remplacées par une plus récente pour la même cible (système, architecture, langue,
          maturité) : aucune machine ne peut plus les installer. Les versions exigées explicitement
          (<code>paquet(=version)</code>) sont conservées.</Text>
        <NumberInput label="Versions précédentes à garder (retour arrière)" min={0} max={10} value={keep}
                     onChange={(v) => { setKeep(Number(v) || 0); setExcluded(new Set()); }} w={300} />
        {isLoading && <Loader />}
        {data && !data.length && <Alert color="green">Rien à nettoyer.</Alert>}
        {data && data.length > 0 && (
          <ScrollArea.Autosize mah={phone ? undefined : "45vh"}>
            <Table fz="sm" verticalSpacing={4}>
              <Table.Thead><Table.Tr><Table.Th /><Table.Th>Paquet</Table.Th><Table.Th>Version</Table.Th>
                <Table.Th>Remplacée par</Table.Th><Table.Th>Cible</Table.Th><Table.Th>Taille</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {data.map((c) => (
                  <Table.Tr key={c.package_uuid} onClick={() => toggle(c.package_uuid)} style={{ cursor: "pointer" }}>
                    <Table.Td><Checkbox checked={!excluded.has(c.package_uuid)} readOnly aria-label="Supprimer" /></Table.Td>
                    <Table.Td>{c.package}</Table.Td><Table.Td>{c.version}</Table.Td><Table.Td>{c.newest}</Table.Td>
                    <Table.Td>{c.target}</Table.Td><Table.Td style={{ whiteSpace: "nowrap" }}>{formatSize(c.size)}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea.Autosize>
        )}
        {error && <Alert color="red">{error}</Alert>}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Annuler</Button>
          <Button color="red" onClick={run} loading={busy} disabled={!chosen.length}>
            Supprimer {chosen.length} version{chosen.length > 1 ? "s" : ""} ({formatSize(total)})
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

/** Delete a whole package (``version`` undefined) or one of its versions. */
export function PackageDeleteDialog({ name, version, onClose, onDeleted }: {
  name: string; version?: string; onClose: () => void; onDeleted: () => void;
}) {
  const refresh = useRefresh();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [blockers, setBlockers] = useState<Record<string, unknown> | null>(null);
  const usage = useQuery({
    queryKey: ["package-usage", name],
    queryFn: () => api.get<PackageUsage>(`/api/packages/${encodeURIComponent(name)}/usage`),
    enabled: !version,
  });
  const used = !version && usage.data && (usage.data.dependents.length > 0 || usage.data.hosts.length > 0);
  const remove = async () => {
    setBusy(true);
    setError("");
    try {
      await api.delete(`/api/packages/${encodeURIComponent(name)}${version ? `?version=${encodeURIComponent(version)}` : ""}`);
      notifications.show({ color: "green", title: "Supprimé", message: version ? `${name} ${version}` : name });
      refresh();
      onDeleted();
      onClose();
    } catch (e) {
      setError((e as Error).message);
      if (e instanceof ApiError && e.status === 409) setBlockers(e.detail ?? null);
    } finally {
      setBusy(false);
    }
  };
  const reasons = blockers ?? (used ? usage.data as unknown as Record<string, unknown> : null);
  const list = (key: string) => (reasons?.[key] as string[] | undefined) ?? [];
  return (
    <Modal opened onClose={onClose} title={version ? `Supprimer ${name} ${version}` : `Supprimer ${name}`} centered>
      <Stack>
        {!version && usage.isLoading && <Loader size="sm" />}
        {reasons && (list("dependents").length > 0 || list("hosts").length > 0 || list("pinned").length > 0) ? (
          <Alert color="orange" title="Encore utilisé : suppression impossible">
            {list("dependents").length > 0 && <Text size="sm">Paquets et groupes qui en dépendent : {list("dependents").join(", ")}</Text>}
            {list("hosts").length > 0 && <Text size="sm">Machines qui l'ont dans leur paquet machine : {list("hosts").join(", ")}</Text>}
            {list("pinned").length > 0 && <Text size="sm">Exigé explicitement : {list("pinned").join(", ")}</Text>}
            <Text size="xs" mt="xs">Retirez-le d'abord de ces paquets et machines (affectation).</Text>
          </Alert>
        ) : (
          <Text size="sm">{version ? "Cette version sera supprimée du dépôt."
            : "Toutes les versions du paquet seront supprimées du dépôt. Les machines qui l'ont installé le gardent."}</Text>
        )}
        {error && !blockers && <Alert color="red">{error}</Alert>}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Annuler</Button>
          <Button color="red" onClick={remove} loading={busy} disabled={!!used || !!blockers}>Supprimer</Button>
        </Group>
      </Stack>
    </Modal>
  );
}

// --- remove hosts from the inventory -------------------------------------------------------------------------

interface HostTarget { uuid: string; name: string }

const Ctx = createContext<(targets: HostTarget[]) => void>(() => {});
export const useDeleteHosts = () => useContext(Ctx);

export function RepoAdminProvider({ children }: { children: ReactNode }) {
  const [targets, setTargets] = useState<HostTarget[] | null>(null);
  const open = useCallback((t: HostTarget[]) => setTargets(t), []);
  return (
    <Ctx.Provider value={open}>
      {children}
      {targets && <HostsDeleteDialog targets={targets} onClose={() => setTargets(null)} />}
    </Ctx.Provider>
  );
}

function HostsDeleteDialog({ targets, onClose }: { targets: HostTarget[]; onClose: () => void }) {
  const phone = useMediaQuery("(max-width: 48em)");
  const refresh = useRefresh();
  const [withPackages, setWithPackages] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const n = targets.length;
  const needCount = n >= TYPE_COUNT_FROM;
  const run = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await api.post<{ hosts: number; files: number }>("/api/hosts/delete",
        { hosts: targets.map((t) => t.uuid), delete_packages: withPackages });
      notifications.show({ color: "green", title: "Inventaire",
        message: `${r.hosts} machine(s) retirée(s)${r.files ? `, ${r.files} paquet(s) machine supprimé(s)` : ""}` });
      refresh();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal opened onClose={onClose} title="Retirer de l'inventaire" fullScreen={!!phone} centered>
      <Stack>
        <Text size="sm">{n} machine{n > 1 ? "s" : ""} :</Text>
        <List size="sm" style={{ maxHeight: 180, overflow: "auto" }}>
          {targets.map((t) => <List.Item key={t.uuid}>{t.name}</List.Item>)}
        </List>
        <Alert color="orange">Leurs données d'inventaire sont effacées du serveur WAPT. Une machine dont l'agent est
          toujours actif se réenregistre à sa prochaine remontée : réservez ceci aux machines disparues ou réinstallées.</Alert>
        <Checkbox label="Supprimer aussi leur paquet machine (paquets et groupes affectés)" checked={withPackages}
                  onChange={(e) => setWithPackages(e.currentTarget.checked)} />
        {needCount && <TextInput label={`Pour confirmer, saisissez le nombre de machines (${n})`} value={typed}
                                 onChange={(e) => setTyped(e.currentTarget.value)} inputMode="numeric" />}
        {error && <Alert color="red">{error}</Alert>}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Annuler</Button>
          <Button color="red" onClick={run} loading={busy} disabled={needCount && typed.trim() !== String(n)}>Retirer</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
