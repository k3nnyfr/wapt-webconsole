// Group packages: create, edit (description, content, conflicts) and delete, signed with the user's key.

import { Alert, Button, Group, Modal, MultiSelect, Stack, Text, TextInput, Textarea } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, type RepoPackage, api } from "../api";
import { useRepoOptions } from "./assign";
import { useSigning } from "./signing";

const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._+~-]{0,199}$/;

function useSigned() {
  const { ensureUnlocked } = useSigning();
  return async <T,>(call: () => Promise<T>): Promise<T | null> => {
    if (!(await ensureUnlocked())) return null;
    try {
      return await call();
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 423) || !(await ensureUnlocked())) throw e;
      return await call();
    }
  };
}

function useRefresh() {
  const queryClient = useQueryClient();
  return () => {
    for (const key of [["packages"], ["package"], ["journal"], ["host"]]) {
      void queryClient.invalidateQueries({ queryKey: key });
    }
  };
}

/** Create a group (``group`` undefined) or edit one. */
export function GroupEditor({ group, onClose, onSaved }: {
  group?: RepoPackage; onClose: () => void; onSaved?: (name: string) => void;
}) {
  const phone = useMediaQuery("(max-width: 48em)");
  const options = useRepoOptions();
  const signed = useSigned();
  const refresh = useRefresh();
  const [name, setName] = useState(group?.package ?? "grp-");
  const [description, setDescription] = useState(group?.description ?? "");
  const [depends, setDepends] = useState<string[]>(group?.depends ?? []);
  const [conflicts, setConflicts] = useState<string[]>(group?.conflicts ?? []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const choices = options.map((g) => ({ ...g, items: g.items.filter((i) => i.value !== name) }));

  const save = async () => {
    setBusy(true);
    setError("");
    const body = { name, description, depends, conflicts, expected_version: group?.version ?? null };
    try {
      const result = await signed(() => group
        ? api.put<{ version: string }>(`/api/groups/${encodeURIComponent(name)}`, body)
        : api.post<{ version: string }>("/api/groups", body));
      if (!result) return;
      notifications.show({ color: "green", title: group ? "Groupe modifié" : "Groupe créé",
        message: `${name}, version ${result.version}` });
      refresh();
      onSaved?.(name);
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal opened onClose={onClose} title={group ? `Modifier ${group.package}` : "Nouveau groupe"} size="lg"
           fullScreen={!!phone}>
      <Stack>
        {error && <Alert color="red">{error}</Alert>}
        <TextInput label="Nom du paquet groupe" value={name} onChange={(e) => setName(e.currentTarget.value.trim())}
                   disabled={!!group} error={name && !NAME_RE.test(name) ? "lettres, chiffres, . _ + ~ -" : undefined}
                   description={group ? undefined : "Convention : préfixe grp-, par exemple grp-compta"} />
        <Textarea label="Description" value={description} onChange={(e) => setDescription(e.currentTarget.value)}
                  maxLength={500} autosize minRows={2} />
        <MultiSelect label="Contenu" description="Paquets et groupes installés sur les machines du groupe"
                     data={choices} value={depends} onChange={setDepends} searchable maxDropdownHeight={260} />
        <MultiSelect label="Conflits" description="Paquets à désinstaller des machines du groupe"
                     data={choices} value={conflicts} onChange={setConflicts} searchable maxDropdownHeight={260} />
        <Text size="xs" c="dimmed">Le groupe est signé avec votre clé et publié dans le dépôt ; les machines qui l'ont
          dans leur paquet machine appliquent les changements à leur prochaine mise à jour.</Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Annuler</Button>
          <Button onClick={save} loading={busy} disabled={!NAME_RE.test(name) || (!group && name === "grp-")}>
            Signer et publier
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

export function GroupDelete({ group, onClose, onDeleted }: {
  group: RepoPackage; onClose: () => void; onDeleted: () => void;
}) {
  const refresh = useRefresh();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const remove = async () => {
    setBusy(true);
    setError("");
    try {
      await api.delete(`/api/groups/${encodeURIComponent(group.package)}?expected_version=${encodeURIComponent(group.version)}`);
      notifications.show({ color: "green", title: "Groupe supprimé", message: group.package });
      refresh();
      onDeleted();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal opened onClose={onClose} title={`Supprimer ${group.package}`} centered>
      <Stack>
        {error && <Alert color="red">{error}</Alert>}
        <Text size="sm">Toutes les versions du groupe seront supprimées du dépôt. La suppression est refusée tant que
          des machines l'ont dans leur paquet machine : retirez-le d'abord de ces machines.</Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Annuler</Button>
          <Button color="red" onClick={remove} loading={busy}>Supprimer</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
