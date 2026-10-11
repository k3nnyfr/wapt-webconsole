// Signing key of the actions and packages, unlocked per session for a limited time (backend signing.py).
// The user brings the encrypted private key and its certificate from their device (file chooser) and types the
// passphrase. The files stay in this tab's memory only (never in browser storage), to unlock again after expiry.
// ensureUnlocked() asks for them when needed and tells whether signing is open.

import { ActionIcon, Button, FileInput, Group, Menu, Modal, PasswordInput, Stack, Text,
  Tooltip } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { IconKey, IconLock, IconLockOpen } from "@tabler/icons-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, createContext, useCallback, useContext, useRef, useState } from "react";

import { ApiError, type Me, type SigningStatus, api, roleAtLeast } from "../api";

interface SigningContext {
  status: SigningStatus | undefined;
  ensureUnlocked: () => Promise<boolean>;
  lock: () => Promise<void>;
}

interface KeyMaterial {
  key_pem: string;
  certificate_pem: string;
  names: string[];
}

/** Encrypted key and certificate chosen in this tab: memory only, lost when the page is closed or reloaded. */
let remembered: KeyMaterial | null = null;

async function readKeyFiles(files: File[]): Promise<KeyMaterial> {
  const texts = await Promise.all(files.map((f) => f.text()));
  const keys = texts.map((t) => t.match(/-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/))
    .filter(Boolean).map((m) => m![0]);
  const certs = texts.flatMap((t) => t.match(/-----BEGIN CERTIFICATE-----[\s\S]*?-----END CERTIFICATE-----/g) ?? []);
  if (keys.length !== 1) throw new Error("Choisissez un seul fichier de clé privée (PEM).");
  if (!keys[0].includes("ENCRYPTED")) throw new Error("La clé privée doit être protégée par une passphrase.");
  if (!certs.length) throw new Error("Ajoutez le certificat (.crt) de la clé.");
  return { key_pem: keys[0] + "\n", certificate_pem: certs.join("\n") + "\n", names: files.map((f) => f.name) };
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
  const [material, setMaterial] = useState<KeyMaterial | null>(remembered);
  const [files, setFiles] = useState<File[]>([]);
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

  const chooseFiles = async (chosen: File[]) => {
    setFiles(chosen);
    setError("");
    if (!chosen.length) return;
    try {
      const read = await readKeyFiles(chosen);
      remembered = read;
      setMaterial(read);
    } catch (e) {
      setMaterial(null);
      setError((e as Error).message);
    }
  };

  const unlock = async () => {
    setBusy(true);
    setError("");
    try {
      await api.post("/api/signing/unlock", { passphrase, ...(material
        ? { key_pem: material.key_pem, certificate_pem: material.certificate_pem } : {}) });
      await queryClient.invalidateQueries({ queryKey: ["signing"] });
      finish(true);
    } catch (e) {
      setPassphrase("");
      setError(e instanceof ApiError && e.status === 403 ? "Passphrase incorrecte." : (e as Error).message);
      if (e instanceof ApiError && e.status === 422) { remembered = null; setMaterial(null); setFiles([]); }
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
              Les actions et les paquets sont signés avec votre clé. Choisissez sa clé privée chiffrée et son
              certificat sur votre appareil, puis saisissez la passphrase : la signature reste ouverte
              {" "}{Math.round((status?.ttl ?? 1800) / 60)} minutes pour votre session uniquement.
            </Text>
            {material ? (
              <Group justify="space-between" wrap="nowrap">
                <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
                  <IconKey size={16} />
                  <Text size="sm" truncate>{material.names.join(", ")}</Text>
                </Group>
                <Button size="compact-xs" variant="subtle"
                        onClick={() => { remembered = null; setMaterial(null); setFiles([]); }}>Changer</Button>
              </Group>
            ) : (
              <FileInput label="Clé privée et certificat" multiple clearable value={files}
                         onChange={(f) => void chooseFiles(f)} accept=".pem,.key,.crt,.cer,application/x-pem-file"
                         placeholder="Choisir les fichiers .pem et .crt" leftSection={<IconKey size={16} />}
                         description={status?.server_key
                           ? "Facultatif : sans fichier, la clé enregistrée sur le serveur de la console est utilisée."
                           : "La clé reste chiffrée ; le serveur ne la garde qu'en mémoire, le temps du déverrouillage."} />
            )}
            <PasswordInput label="Passphrase" value={passphrase} onChange={(e) => setPassphrase(e.currentTarget.value)}
                           autoComplete="off" name="wwc-signing-passphrase" data-1p-ignore data-lpignore="true"
                           autoFocus={!!material} error={error || undefined} />
            <Group justify="flex-end">
              <Button variant="default" onClick={() => finish(false)}>Annuler</Button>
              <Button type="submit" loading={busy}
                      disabled={!passphrase || (!material && !status?.server_key)}>Déverrouiller</Button>
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
  if (!roleAtLeast(me.user.role, "operator") || !status) return null;
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
        <Menu.Label>{status.identity.cn} · encore {Math.ceil(status.expires_in / 60)} min</Menu.Label>
        <Menu.Item leftSection={<IconLock size={16} />} onClick={() => void lock()}>Verrouiller maintenant</Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}
