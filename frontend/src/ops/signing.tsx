// Signing key of the actions: unlocked per session by typing its passphrase, for a limited time (backend
// signing.py). ensureUnlocked() asks for the passphrase when needed and tells whether the key is open.

import { ActionIcon, Alert, Button, Group, Menu, Modal, PasswordInput, Stack, Text, Tooltip } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { IconLock, IconLockOpen } from "@tabler/icons-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, createContext, useCallback, useContext, useRef, useState } from "react";

import { ApiError, type Me, type SigningStatus, api, roleAtLeast } from "../api";

interface SigningContext {
  status: SigningStatus | undefined;
  ensureUnlocked: () => Promise<boolean>;
  lock: () => Promise<void>;
}

const Ctx = createContext<SigningContext>({
  status: undefined, ensureUnlocked: async () => false, lock: async () => {},
});

export const useSigning = () => useContext(Ctx);

export function SigningProvider({ me, children }: { me: Me; children: ReactNode }) {
  const queryClient = useQueryClient();
  const phone = useMediaQuery("(max-width: 48em)");
  const operator = roleAtLeast(me.user.role, "operator");
  const { data: status } = useQuery({
    queryKey: ["signing"],
    queryFn: () => api.get<SigningStatus>("/api/signing"),
    refetchInterval: 30_000,
    enabled: operator,
  });
  const [opened, setOpened] = useState(false);
  const [passphrase, setPassphrase] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const waiting = useRef<((ok: boolean) => void) | null>(null);

  const finish = (ok: boolean) => {
    setOpened(false);
    setPassphrase("");
    setError("");
    waiting.current?.(ok);
    waiting.current = null;
  };

  const ensureUnlocked = useCallback(async () => {
    const fresh = await queryClient.fetchQuery({ queryKey: ["signing"],
      queryFn: () => api.get<SigningStatus>("/api/signing"), staleTime: 0 });
    if (fresh.unlocked) return true;
    return new Promise<boolean>((resolve) => {
      waiting.current = resolve;
      setOpened(true);
    });
  }, [queryClient]);

  const unlock = async () => {
    setBusy(true);
    setError("");
    try {
      await api.post("/api/signing/unlock", { passphrase });
      await queryClient.invalidateQueries({ queryKey: ["signing"] });
      finish(true);
    } catch (e) {
      setPassphrase("");
      setError(e instanceof ApiError && e.status === 403 ? "Passphrase incorrecte." : (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const lock = async () => {
    await api.post("/api/signing/lock");
    await queryClient.invalidateQueries({ queryKey: ["signing"] });
  };

  return (
    <Ctx.Provider value={{ status, ensureUnlocked, lock }}>
      {children}
      <Modal opened={opened} onClose={() => finish(false)} title="Déverrouiller la clé de signature"
             fullScreen={!!phone} centered>
        <form onSubmit={(e) => { e.preventDefault(); void unlock(); }}>
          <Stack>
            <Text size="sm">
              Les actions envoyées aux machines sont signées avec la clé de {status?.identity.cn || "l'administrateur WAPT"}.
              Saisissez sa passphrase : la clé restera ouverte {Math.round((status?.ttl ?? 1800) / 60)} minutes
              pour votre session uniquement.
            </Text>
            {!status?.configured && (
              <Alert color="orange">Aucune clé de signature n'est configurée sur le serveur de la console.</Alert>
            )}
            <PasswordInput label="Passphrase" value={passphrase} onChange={(e) => setPassphrase(e.currentTarget.value)}
                           autoComplete="off" name="wwc-signing-passphrase" data-1p-ignore data-lpignore="true"
                           autoFocus error={error || undefined} disabled={!status?.configured} />
            <Group justify="flex-end">
              <Button variant="default" onClick={() => finish(false)}>Annuler</Button>
              <Button type="submit" loading={busy} disabled={!passphrase || !status?.configured}>Déverrouiller</Button>
            </Group>
          </Stack>
        </form>
      </Modal>
    </Ctx.Provider>
  );
}

/** Header button: key state, unlock or lock. */
export function KeyButton({ me }: { me: Me }) {
  const { status, ensureUnlocked, lock } = useSigning();
  if (!roleAtLeast(me.user.role, "operator") || !status?.configured) return null;
  if (!status.unlocked) {
    return (
      <Tooltip label="Clé de signature verrouillée : cliquer pour la déverrouiller">
        <ActionIcon variant="subtle" color="gray" size="lg" onClick={() => void ensureUnlocked()}
                    aria-label="Déverrouiller la clé">
          <IconLock size={18} />
        </ActionIcon>
      </Tooltip>
    );
  }
  return (
    <Menu position="bottom-end" shadow="md">
      <Menu.Target>
        <Tooltip label={`Clé ouverte encore ${Math.ceil(status.expires_in / 60)} min`}>
          <ActionIcon variant="light" color="green" size="lg" aria-label="Clé déverrouillée">
            <IconLockOpen size={18} />
          </ActionIcon>
        </Tooltip>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>Clé ouverte encore {Math.ceil(status.expires_in / 60)} min</Menu.Label>
        <Menu.Item leftSection={<IconLock size={16} />} onClick={() => void lock()}>Verrouiller maintenant</Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}
