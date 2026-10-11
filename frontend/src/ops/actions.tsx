// Remote actions: dialogs (packages, description), confirmation, key unlock, sending, report.
// hostMenu() builds the action menu of one host or of a selection, filtered by role and connection.

import { Alert, Button, Group, List, Modal, MultiSelect, Stack, Switch, Text, TextInput } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import {
  IconBolt,
  IconCopy,
  IconDownload,
  IconEraser,
  IconId,
  IconListCheck,
  IconPackage,
  IconPencil,
  IconPlayerStop,
  IconPlugConnected,
  IconPower,
  IconRefresh,
  IconRotateClockwise,
  IconTrash,
  IconUpload,
} from "@tabler/icons-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, createContext, useCallback, useContext, useRef, useState } from "react";

import { type ActionName, type ActionResult, ApiError, type Host, type Me, type RepoPackage, api,
  roleAtLeast } from "../api";
import type { Action } from "../components/ActionMenu";
import { useSigning } from "./signing";

export interface Target {
  uuid: string;
  name: string;
  connected?: boolean;
}

interface Options {
  packages?: string[];
  force?: boolean;
}

const LABELS: Record<ActionName, string> = {
  update: "Mettre à jour l'index",
  upgrade: "Appliquer les mises à jour",
  install: "Installer des paquets",
  inventory: "Remonter l'inventaire",
  audit: "Lancer l'audit des paquets",
  cancel: "Annuler les tâches",
  wol: "Réveiller (Wake-on-LAN)",
  remove: "Désinstaller",
  forget: "Oublier (sans désinstaller)",
  description: "Changer la description",
  restart_agent: "Redémarrer l'agent WAPT",
  reboot: "Redémarrer la machine",
  shutdown: "Éteindre la machine",
};
const ALWAYS_CONFIRM: ActionName[] = ["remove", "forget", "cancel", "restart_agent", "reboot", "shutdown"];
const TYPE_COUNT_FROM = 10;           // above this many hosts, the count must be typed to confirm

type Dialog =
  | { kind: "confirm"; action: ActionName; targets: Target[]; packages: string[]; resolve: (ok: boolean) => void }
  | { kind: "packages"; targets: Target[]; resolve: (packages: string[] | null, force: boolean) => void }
  | { kind: "description"; target: Target; resolve: (value: string | null) => void };

const Ctx = createContext<(action: ActionName, targets: Target[], options?: Options) => Promise<void>>(
  async () => {});

export const useRunAction = () => useContext(Ctx);

export function ActionsProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const { ensureUnlocked } = useSigning();
  const [dialog, setDialog] = useState<Dialog | null>(null);

  const ask = <T,>(make: (resolve: (v: T) => void) => Dialog) =>
    new Promise<T>((resolve) => setDialog(make(resolve)));

  const run = useCallback(async (action: ActionName, targets: Target[], options: Options = {}) => {
    let packages = options.packages ?? [];
    let force = options.force ?? false;
    let description: string | undefined;
    if (action === "install" && !packages.length) {
      const [chosen, f] = await ask<[string[] | null, boolean]>((resolve) => ({
        kind: "packages", targets, resolve: (p, f) => resolve([p, f]) }));
      if (!chosen?.length) return;
      packages = chosen;
      force = f;
    }
    if (action === "description") {
      const value = await ask<string | null>((resolve) => ({ kind: "description", target: targets[0], resolve }));
      if (value === null) return;
      description = value;
    }
    if (ALWAYS_CONFIRM.includes(action) || targets.length > 1) {
      const ok = await ask<boolean>((resolve) => ({ kind: "confirm", action, targets, packages, resolve }));
      if (!ok) return;
    }
    const body = { action, hosts: targets.map((t) => t.uuid), packages, description, force };
    const send = () => api.post<ActionResult>("/api/actions", body);
    try {
      if (action !== "wol" && !(await ensureUnlocked())) return;
      let result: ActionResult;
      try {
        result = await send();
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 423) || !(await ensureUnlocked())) throw e;
        result = await send();                       // the key expired in between: unlocked again, retried once
      }
      notifications.show({
        color: result.reached.length ? "green" : "orange",
        title: result.label,
        message: (
          <>
            {result.message}
            {result.skipped.length > 0 && (
              <Text size="sm" c="orange">
                Non joignables (déconnectées) : {result.skipped.map((t) => t.name).join(", ")}
              </Text>
            )}
          </>
        ),
        autoClose: result.skipped.length ? 10_000 : 5_000,
      });
      for (const key of [["hosts"], ["host"], ["host-packages"], ["host-tasks"], ["journal"]]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
    } catch (e) {
      notifications.show({ color: "red", title: LABELS[action], message: (e as Error).message, autoClose: 10_000 });
    }
  }, [ensureUnlocked, queryClient]);

  return (
    <Ctx.Provider value={run}>
      {children}
      {dialog?.kind === "confirm" && <ConfirmDialog dialog={dialog} close={() => setDialog(null)} />}
      {dialog?.kind === "packages" && <PackagesDialog dialog={dialog} close={() => setDialog(null)} />}
      {dialog?.kind === "description" && <DescriptionDialog dialog={dialog} close={() => setDialog(null)} />}
    </Ctx.Provider>
  );
}

function ConfirmDialog({ dialog, close }: { dialog: Extract<Dialog, { kind: "confirm" }>; close: () => void }) {
  const phone = useMediaQuery("(max-width: 48em)");
  const [typed, setTyped] = useState("");
  const n = dialog.targets.length;
  const needCount = n >= TYPE_COUNT_FROM;
  const answer = (ok: boolean) => { close(); dialog.resolve(ok); };
  const offline = dialog.action === "wol" ? [] : dialog.targets.filter((t) => t.connected === false);
  return (
    <Modal opened onClose={() => answer(false)} title={LABELS[dialog.action]} fullScreen={!!phone} centered>
      <Stack>
        <Text size="sm">
          {LABELS[dialog.action]}
          {dialog.packages.length > 0 && <> : <b>{dialog.packages.join(", ")}</b></>} sur <b>{n} machine{n > 1 ? "s" : ""}</b> :
        </Text>
        <List size="sm" spacing={2} style={{ maxHeight: 200, overflow: "auto" }}>
          {dialog.targets.map((t) => <List.Item key={t.uuid}>{t.name}</List.Item>)}
        </List>
        {offline.length > 0 && (
          <Alert color="orange">
            {offline.length} machine{offline.length > 1 ? "s sont déconnectées" : " est déconnectée"} :
            le serveur ne pourra pas lui transmettre l'action.
          </Alert>
        )}
        {needCount && (
          <TextInput label={`Pour confirmer, saisissez le nombre de machines (${n})`} value={typed}
                     onChange={(e) => setTyped(e.currentTarget.value)} inputMode="numeric" autoFocus />
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={() => answer(false)}>Annuler</Button>
          <Button color={ALWAYS_CONFIRM.includes(dialog.action) ? "red" : "blue"}
                  disabled={needCount && typed.trim() !== String(n)} onClick={() => answer(true)}>
            Confirmer
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function PackagesDialog({ dialog, close }: { dialog: Extract<Dialog, { kind: "packages" }>; close: () => void }) {
  const phone = useMediaQuery("(max-width: 48em)");
  const [chosen, setChosen] = useState<string[]>([]);
  const [force, setForce] = useState(false);
  const packages = useQuery({ queryKey: ["packages", "package"],
    queryFn: () => api.get<RepoPackage[]>("/api/packages?kind=package") });
  const groups = useQuery({ queryKey: ["packages", "group"],
    queryFn: () => api.get<RepoPackage[]>("/api/packages?kind=group") });
  const option = (p: RepoPackage) => ({ value: p.package, label: p.name ? `${p.name} (${p.package})` : p.package });
  const data = [
    { group: "Paquets", items: (packages.data ?? []).map(option) },
    { group: "Groupes", items: (groups.data ?? []).map(option) },
  ];
  const answer = (value: string[] | null) => { close(); dialog.resolve(value, force); };
  return (
    <Modal opened onClose={() => answer(null)} title="Installer des paquets" fullScreen={!!phone} centered>
      <Stack>
        <Text size="sm">Sur {dialog.targets.map((t) => t.name).join(", ")}</Text>
        <MultiSelect label="Paquets du dépôt" placeholder="Rechercher un paquet" data={data} value={chosen}
                     onChange={setChosen} searchable nothingFoundMessage="Aucun paquet" maxDropdownHeight={300}
                     comboboxProps={{ withinPortal: true }} />
        <Switch label="Forcer (réinstaller même si déjà installé)" checked={force}
                onChange={(e) => setForce(e.currentTarget.checked)} />
        <Text size="xs" c="dimmed">
          Installation immédiate par l'agent, sans modifier le paquet machine : pour que la machine garde ce paquet,
          l'affecter à la machine (v0.5).
        </Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={() => answer(null)}>Annuler</Button>
          <Button disabled={!chosen.length} onClick={() => answer(chosen)}>Continuer</Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function DescriptionDialog({ dialog, close }: { dialog: Extract<Dialog, { kind: "description" }>; close: () => void }) {
  const [value, setValue] = useState("");
  const answer = (v: string | null) => { close(); dialog.resolve(v); };
  return (
    <Modal opened onClose={() => answer(null)} title={`Description de ${dialog.target.name}`} centered>
      <form onSubmit={(e) => { e.preventDefault(); answer(value.trim()); }}>
        <Stack>
          <TextInput label="Nouvelle description" value={value} onChange={(e) => setValue(e.currentTarget.value)}
                     maxLength={250} autoFocus />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => answer(null)}>Annuler</Button>
            <Button type="submit">Continuer</Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

// --- host menu -----------------------------------------------------------------------------------------------

function copy(text: string, what: string) {
  navigator.clipboard
    .writeText(text)
    .then(() => notifications.show({ message: `${what} copié`, color: "green" }))
    .catch(() => notifications.show({ message: "Copie impossible", color: "red" }));
}

/** Actions of one host (with ``open``: its detail) or of a selection of hosts. */
export function useHostMenu(me: Me) {
  const run = useRunAction();
  const role = me.user.role;
  const runRef = useRef(run);
  runRef.current = run;

  return useCallback((hosts: Host[], open?: (uuid: string) => void): Action[] => {
    const targets: Target[] = hosts.map((h) => ({ uuid: h.uuid, name: h.name, connected: h.connected }));
    const anyConnected = hosts.some((h) => h.connected);
    const anyOffline = hosts.some((h) => !h.connected);
    const operator = roleAtLeast(role, "operator");
    const admin = roleAtLeast(role, "admin");
    const offlineHint = "machine déconnectée";
    const act = (name: ActionName, icon: ReactNode, opts: { admin?: boolean; color?: string; hidden?: boolean;
                  disabled?: boolean; hint?: string } = {}): Action[] => {
      if (opts.hidden || !(opts.admin ? admin : operator)) return [];
      const disabled = opts.disabled ?? (name !== "wol" && !anyConnected);
      return [{ key: name, label: LABELS[name] + (name === "install" || name === "description" ? "…" : ""), icon,
                color: opts.color, disabled, hint: disabled ? (opts.hint ?? offlineHint) : undefined,
                onClick: () => void runRef.current(name, targets) }];
    };
    const single = hosts.length === 1 ? hosts[0] : null;
    return [
      ...(single && open ? [{ key: "open", label: "Ouvrir la fiche", icon: <IconId size={16} />,
                              onClick: () => open(single.uuid) }] : []),
      ...act("update", <IconRefresh size={16} />),
      ...act("upgrade", <IconDownload size={16} />),
      ...act("install", <IconPackage size={16} />),
      ...act("inventory", <IconUpload size={16} />),
      ...act("audit", <IconListCheck size={16} />),
      ...act("wol", <IconPlugConnected size={16} />, { hidden: !anyOffline }),
      ...act("cancel", <IconPlayerStop size={16} />),
      ...act("description", <IconPencil size={16} />, { admin: true, hidden: !single }),
      ...act("restart_agent", <IconRotateClockwise size={16} />, { admin: true }),
      ...act("reboot", <IconBolt size={16} />, { admin: true, color: "red",
        disabled: !hosts.some((h) => h.connected && h.reboot_allowed), hint: "non autorisé par l'agent" }),
      ...act("shutdown", <IconPower size={16} />, { admin: true, color: "red",
        disabled: !hosts.some((h) => h.connected && h.shutdown_allowed), hint: "non autorisé par l'agent" }),
      ...(single ? [
        { key: "copy-name", label: "Copier le nom", icon: <IconCopy size={16} />, onClick: () => copy(single.name, "Nom") },
        ...(single.main_ip ? [{ key: "copy-ip", label: "Copier l'adresse IP", icon: <IconCopy size={16} />,
                                onClick: () => copy(single.main_ip, "Adresse IP") }] : []),
      ] : []),
    ];
  }, [role]);
}

/** Actions on one package of one host (host detail, Packages tab). */
export function usePackageMenu(me: Me) {
  const run = useRunAction();
  return (host: Target, packageName: string): Action[] => {
    const operator = roleAtLeast(me.user.role, "operator");
    const admin = roleAtLeast(me.user.role, "admin");
    const offline = host.connected === false;
    const item = (key: ActionName, label: string, icon: ReactNode, force = false, color?: string): Action => ({
      key: key + (force ? "-force" : ""), label, icon, color, disabled: offline, hint: offline ? "machine déconnectée" : undefined,
      onClick: () => void run(key, [host], { packages: [packageName], force }),
    });
    return [
      ...(operator ? [item("install", "Installer ou mettre à jour", <IconDownload size={16} />),
                      item("install", "Réinstaller (forcer)", <IconRefresh size={16} />, true)] : []),
      ...(admin ? [item("remove", "Désinstaller", <IconTrash size={16} />, false, "red"),
                   item("forget", "Oublier (sans désinstaller)", <IconEraser size={16} />)] : []),
    ];
  };
}
