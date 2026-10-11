// Import from the store: plan (dependencies, sizes, refusals), signing key, then follow the background job.

import { Alert, Badge, Button, Group, Loader, Modal, Progress, ScrollArea, Stack, Switch, Table, Text } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, type Job, type JobItem, type StorePlan, api } from "../api";
import { useSigning } from "../ops/signing";
import { formatSize } from "../repo/common";

const STEPS: Record<JobItem["status"], { label: string; color: string }> = {
  waiting: { label: "en attente", color: "gray" },
  downloading: { label: "téléchargement", color: "blue" },
  signing: { label: "vérification et signature", color: "blue" },
  uploading: { label: "envoi au dépôt", color: "blue" },
  done: { label: "importé", color: "green" },
  error: { label: "échec", color: "red" },
};

export function JobProgress({ jobId }: { jobId: string }) {
  const queryClient = useQueryClient();
  const { data: job } = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.get<Job>(`/api/jobs/${jobId}`),
    refetchInterval: (q) => {
      const status = (q.state.data as Job | undefined)?.status;
      if (status && status !== "running") {
        for (const key of [["store"], ["packages"], ["journal"], ["jobs"]]) {
          void queryClient.invalidateQueries({ queryKey: key });
        }
        return false;
      }
      return 1000;
    },
  });
  if (!job) return <Loader />;
  const done = job.items.filter((i) => i.status === "done" || i.status === "error").length;
  return (
    <Stack gap="sm">
      <Group justify="space-between">
        <Text size="sm" fw={600}>
          {job.status === "running" ? `Import en cours : ${done} / ${job.items.length}` : job.message}
        </Text>
        <Badge color={job.status === "done" ? "green" : job.status === "failed" ? "red" : "blue"} variant="light">
          {job.status === "running" ? "en cours" : job.status === "done" ? "terminé" : "terminé avec des erreurs"}
        </Badge>
      </Group>
      <Progress value={(done / Math.max(1, job.items.length)) * 100} animated={job.status === "running"} />
      <Stack gap={6}>
        {job.items.map((item, i) => (
          <Stack key={`${item.name}-${item.target}-${i}`} gap={2}>
            <Group justify="space-between" wrap="nowrap" gap="xs">
              <Text size="sm" truncate>{item.name} {item.imported_version || item.version}
                <Text span size="xs" c="dimmed"> · {item.target}</Text></Text>
              <Badge size="sm" variant="light" color={STEPS[item.status].color} style={{ flexShrink: 0 }}>
                {STEPS[item.status].label}
              </Badge>
            </Group>
            {item.status === "downloading" && <Progress size="xs" value={item.progress * 100} />}
            {item.error && <Text size="xs" c="red">{item.error}</Text>}
          </Stack>
        ))}
      </Stack>
      {job.status === "running" && (
        <Text size="xs" c="dimmed">Vous pouvez fermer cette fenêtre : l'import continue, il reste visible dans l'onglet Imports.</Text>
      )}
    </Stack>
  );
}

export default function ImportDialog({ names, onClose }: { names: string[]; onClose: () => void }) {
  const phone = useMediaQuery("(max-width: 48em)");
  const { ensureUnlocked } = useSigning();
  const [withDeps, setWithDeps] = useState(true);
  const [jobId, setJobId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const plan = useQuery({
    queryKey: ["store-plan", names, withDeps],
    queryFn: () => api.post<StorePlan>("/api/store/plan", { names, with_dependencies: withDeps }),
    enabled: !jobId,
  });

  const start = async () => {
    if (!(await ensureUnlocked())) return;
    setBusy(true);
    setError("");
    const body = { names, with_dependencies: withDeps };
    try {
      let job: Job;
      try {
        job = await api.post<Job>("/api/store/import", body);
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 423) || !(await ensureUnlocked())) throw e;
        job = await api.post<Job>("/api/store/import", body);
      }
      setJobId(job.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const p = plan.data;
  return (
    <Modal opened onClose={onClose} title="Importer depuis le store" size="xl" fullScreen={!!phone}>
      {jobId ? (
        <Stack>
          <JobProgress jobId={jobId} />
          <Group justify="flex-end"><Button onClick={onClose}>Fermer</Button></Group>
        </Stack>
      ) : (
        <Stack>
          <Text size="sm">
            Chaque paquet est téléchargé, sa signature Tranquil IT vérifiée, puis il est renommé
            {p ? ` ${p.prefix}-…` : ""}, signé avec votre clé et envoyé au dépôt.
          </Text>
          <Switch label="Importer aussi les dépendances absentes du dépôt" checked={withDeps}
                  onChange={(e) => setWithDeps(e.currentTarget.checked)} />
          {plan.isLoading && <Loader />}
          {plan.error && <Alert color="red">{(plan.error as Error).message}</Alert>}
          {p && p.refused.length > 0 && (
            <Alert color="orange">Non importables (réservés à WAPT Enterprise, ou liés à la version du serveur) :
              {" "}{p.refused.join(", ")}</Alert>
          )}
          {p && p.missing.length > 0 && <Alert color="orange">Absents du store pour vos systèmes : {p.missing.join(", ")}</Alert>}
          {p && !p.items.length && <Alert color="green">Rien à importer : le dépôt est à jour.</Alert>}
          {p && p.items.length > 0 && (
            <ScrollArea.Autosize mah={phone ? undefined : "45vh"}>
              <Table fz="sm" verticalSpacing={4}>
                <Table.Thead><Table.Tr><Table.Th>Paquet</Table.Th><Table.Th>Version</Table.Th><Table.Th>Cible</Table.Th>
                  <Table.Th>Taille</Table.Th></Table.Tr></Table.Thead>
                <Table.Tbody>
                  {p.items.map((i) => (
                    <Table.Tr key={i.filename}>
                      <Table.Td>
                        {i.target_name}
                        {i.reason === "dependency" && <Badge size="xs" ml={6} variant="light">dépendance</Badge>}
                      </Table.Td>
                      <Table.Td style={{ whiteSpace: "nowrap" }}>
                        {i.repo_version ? `${i.repo_version} → ${i.version}` : i.version}
                      </Table.Td>
                      <Table.Td>{i.target}</Table.Td>
                      <Table.Td style={{ whiteSpace: "nowrap" }}>{formatSize(i.size)}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </ScrollArea.Autosize>
          )}
          {error && <Alert color="red">{error}</Alert>}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>Annuler</Button>
            <Button onClick={start} loading={busy} disabled={!p?.items.length}>
              Importer {p?.items.length ?? 0} fichier{(p?.items.length ?? 0) > 1 ? "s" : ""}
              {p ? ` (${formatSize(p.size)})` : ""}
            </Button>
          </Group>
        </Stack>
      )}
    </Modal>
  );
}
