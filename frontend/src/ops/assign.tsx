// Assign packages and groups to hosts: choose, preview the host packages before and after, publish.
// The versions seen in the preview are sent back: a host package changed meanwhile is not overwritten.

import { Alert, Badge, Button, Card, Group, List, Loader, Modal, MultiSelect, Stack, Stepper, Switch, Text,
  TextInput } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { ApiError, type AssignmentPreview, type AssignmentResult, type HostsAnswer, type RepoPackage,
  api } from "../api";
import { useSigning } from "./signing";

export interface AssignRequest {
  hosts?: { uuid: string; name: string }[];
  add?: string[];
  remove?: string[];
  pickHosts?: boolean;            // let the user choose the hosts (started from a package or a group)
}

const Ctx = createContext<(request: AssignRequest) => void>(() => {});
export const useAssign = () => useContext(Ctx);

const TYPE_COUNT_FROM = 10;

export function useRepoOptions() {
  const packages = useQuery({ queryKey: ["packages", "package"],
    queryFn: () => api.get<RepoPackage[]>("/api/packages?kind=package") });
  const groups = useQuery({ queryKey: ["packages", "group"],
    queryFn: () => api.get<RepoPackage[]>("/api/packages?kind=group") });
  return useMemo(() => {
    const option = (p: RepoPackage) => ({ value: p.package, label: p.name ? `${p.name} (${p.package})` : p.package });
    return [
      { group: "Groupes", items: (groups.data ?? []).map(option) },
      { group: "Paquets", items: (packages.data ?? []).map(option) },
    ];
  }, [packages.data, groups.data]);
}

export function AssignProvider({ children }: { children: ReactNode }) {
  const [request, setRequest] = useState<AssignRequest | null>(null);
  const open = useCallback((r: AssignRequest) => setRequest(r), []);
  return (
    <Ctx.Provider value={open}>
      {children}
      {request && <AssignDialog request={request} onClose={() => setRequest(null)} />}
    </Ctx.Provider>
  );
}

function Diff({ before, after }: { before: string[]; after: string[] }) {
  const added = after.filter((d) => !before.includes(d));
  const removed = before.filter((d) => !after.includes(d));
  if (!added.length && !removed.length) return <Text size="xs" c="dimmed">inchangé</Text>;
  return (
    <Group gap={4}>
      {added.map((d) => <Badge key={`+${d}`} color="green" variant="light" tt="none">+ {d}</Badge>)}
      {removed.map((d) => <Badge key={`-${d}`} color="red" variant="light" tt="none">− {d}</Badge>)}
    </Group>
  );
}

function AssignDialog({ request, onClose }: { request: AssignRequest; onClose: () => void }) {
  const phone = useMediaQuery("(max-width: 48em)");
  const queryClient = useQueryClient();
  const { ensureUnlocked } = useSigning();
  const repoOptions = useRepoOptions();
  const [step, setStep] = useState(0);
  const [hosts, setHosts] = useState<string[]>(request.hosts?.map((h) => h.uuid) ?? []);
  const [add, setAdd] = useState<string[]>(request.add ?? []);
  const [remove, setRemove] = useState<string[]>(request.remove ?? []);
  const [applyNow, setApplyNow] = useState(false);
  const [typed, setTyped] = useState("");
  const [preview, setPreview] = useState<AssignmentPreview | null>(null);
  const [result, setResult] = useState<AssignmentResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const inventory = useQuery({ queryKey: ["hosts"], queryFn: () => api.get<HostsAnswer>("/api/hosts"),
    enabled: !!request.pickHosts });
  const hostOptions = (inventory.data?.hosts ?? [])
    .map((h) => ({ value: h.uuid, label: h.name })).sort((a, b) => a.label.localeCompare(b.label));

  // current host packages of the chosen hosts: what can be removed
  const current = useQuery({
    queryKey: ["assignment-current", hosts],
    queryFn: () => api.post<AssignmentPreview>("/api/assignments/preview", { hosts }),
    enabled: hosts.length > 0,
  });
  const removable = useMemo(() => [...new Set([...(current.data?.changes.flatMap((c) => c.depends) ?? []),
    ...(request.remove ?? [])])].sort(), [current.data, request.remove]);
  useEffect(() => setTyped(""), [step]);

  const toPreview = async () => {
    setBusy(true);
    setError("");
    try {
      setPreview(await api.post<AssignmentPreview>("/api/assignments/preview", { hosts, add, remove }));
      setStep(1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const changed = preview?.changes.filter((c) => c.changed) ?? [];
  const publish = async () => {
    if (!preview || !(await ensureUnlocked())) return;
    setBusy(true);
    setError("");
    const expected = Object.fromEntries(preview.changes.map((c) => [c.uuid, c.version]));
    const body = { hosts: changed.map((c) => c.uuid), add, remove, expected, apply_now: applyNow };
    try {
      let r: AssignmentResult;
      try {
        r = await api.post<AssignmentResult>("/api/assignments", body);
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 423) || !(await ensureUnlocked())) throw e;
        r = await api.post<AssignmentResult>("/api/assignments", body);
      }
      setResult(r);
      setStep(2);
      notifications.show({ color: r.conflicts.length || r.failed.length ? "orange" : "green",
        title: "Affectation", message: `${r.published.length} paquet(s) machine publié(s)` });
      for (const key of [["host"], ["hosts"], ["packages"], ["package"], ["journal"]]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const needCount = changed.length >= TYPE_COUNT_FROM;
  return (
    <Modal opened onClose={onClose} title="Affecter des paquets et des groupes" size="xl" fullScreen={!!phone}>
      <Stepper active={step} size="sm" mb="md" allowNextStepsSelect={false}>
        <Stepper.Step label="Choix" />
        <Stepper.Step label="Aperçu" />
        <Stepper.Step label="Publication" />
      </Stepper>
      {error && <Alert color="red" mb="sm">{error}</Alert>}

      {step === 0 && (
        <Stack>
          {request.pickHosts ? (
            <MultiSelect label="Machines" data={hostOptions} value={hosts} onChange={setHosts} searchable
                         placeholder="Choisir des machines" maxDropdownHeight={260} />
          ) : (
            <Text size="sm">Machines : {request.hosts?.map((h) => h.name).join(", ")}</Text>
          )}
          <MultiSelect label="Ajouter" description="Paquets ou groupes du dépôt que les machines doivent avoir"
                       data={repoOptions} value={add} onChange={setAdd} searchable maxDropdownHeight={260}
                       nothingFoundMessage="Aucun paquet" />
          <MultiSelect label="Retirer" description="Parmi ce que ces machines ont dans leur paquet machine"
                       data={removable} value={remove} onChange={setRemove} searchable maxDropdownHeight={260}
                       rightSection={current.isFetching ? <Loader size="xs" /> : undefined} />
          <Text size="xs" c="dimmed">
            Retirer un paquet du paquet machine ne le désinstalle pas : WAPT cesse seulement de le maintenir.
            Pour le désinstaller, utiliser l'action « Désinstaller ».
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>Annuler</Button>
            <Button onClick={toPreview} loading={busy} disabled={!hosts.length || (!add.length && !remove.length)}>
              Aperçu
            </Button>
          </Group>
        </Stack>
      )}

      {step === 1 && preview && (
        <Stack>
          {preview.unknown.length > 0 && (
            <Alert color="red" title="Absents du dépôt">{preview.unknown.join(", ")} : retirez-les pour continuer.</Alert>
          )}
          <Text size="sm">{changed.length} paquet{changed.length > 1 ? "s" : ""} machine à publier
            {preview.changes.length - changed.length > 0 && `, ${preview.changes.length - changed.length} inchangé(s)`}
          </Text>
          <Stack gap={6} style={{ maxHeight: phone ? undefined : "45vh", overflow: "auto" }}>
            {preview.changes.map((c) => (
              <Card key={c.uuid} withBorder padding="xs" radius="sm" opacity={c.changed ? 1 : 0.6}>
                <Group justify="space-between" wrap="nowrap" mb={4}>
                  <Text size="sm" fw={500} truncate>{c.name}</Text>
                  <Text size="xs" c="dimmed" style={{ whiteSpace: "nowrap" }}>
                    {c.version ? `version ${c.version} → suivante` : "nouveau paquet machine"}
                  </Text>
                </Group>
                <Diff before={c.depends} after={c.new_depends} />
                {c.conflicts.join() !== c.new_conflicts.join() && (
                  <Text size="xs" c="dimmed" mt={4}>conflits : {c.conflicts.join(", ")} → {c.new_conflicts.join(", ") || "aucun"}</Text>
                )}
              </Card>
            ))}
          </Stack>
          <Switch label="Appliquer maintenant (mise à jour des machines connectées après publication)"
                  checked={applyNow} onChange={(e) => setApplyNow(e.currentTarget.checked)} />
          {needCount && (
            <TextInput label={`Pour confirmer, saisissez le nombre de paquets machine à publier (${changed.length})`}
                       value={typed} onChange={(e) => setTyped(e.currentTarget.value)} inputMode="numeric" />
          )}
          <Group justify="space-between">
            <Button variant="default" onClick={() => setStep(0)}>Retour</Button>
            <Button onClick={publish} loading={busy}
                    disabled={!changed.length || preview.unknown.length > 0 || (needCount && typed.trim() !== String(changed.length))}>
              Signer et publier
            </Button>
          </Group>
        </Stack>
      )}

      {step === 2 && result && (
        <Stack>
          {result.published.length > 0 && (
            <Alert color="green" title={`Publiés (${result.published.length})`}>
              <List size="sm">{result.published.map((p) => (
                <List.Item key={p.uuid}>{p.name} : {p.previous ? `${p.previous} → ${p.version}` : `créé (${p.version})`}</List.Item>
              ))}</List>
            </Alert>
          )}
          {result.conflicts.length > 0 && (
            <Alert color="orange" title="Modifiés entre-temps, non publiés">
              <Text size="sm">{result.conflicts.map((c) => c.name).join(", ")} : leur paquet machine a changé depuis
                l'aperçu (console WAPT ou autre utilisateur). Recommencez l'aperçu pour partir de la version actuelle.</Text>
            </Alert>
          )}
          {result.failed.length > 0 && (
            <Alert color="red" title="Échecs">
              <List size="sm">{result.failed.map((f) => <List.Item key={f.uuid}>{f.name} : {f.error}</List.Item>)}</List>
            </Alert>
          )}
          {result.upgrade && <Text size="sm">Mise à jour des machines connectées : {result.upgrade}</Text>}
          {!applyNow && result.published.length > 0 && (
            <Text size="xs" c="dimmed">Les machines appliqueront les changements à leur prochaine mise à jour.</Text>
          )}
          <Group justify="flex-end">
            {result.conflicts.length > 0 && <Button variant="default" onClick={toPreview}>Recommencer l'aperçu</Button>}
            <Button onClick={onClose}>Fermer</Button>
          </Group>
        </Stack>
      )}
    </Modal>
  );
}
