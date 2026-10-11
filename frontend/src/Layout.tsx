// Application shell: side navigation on a computer or tablet, bottom navigation bar on a phone.

import { ActionIcon, AppShell, Group, NavLink, Stack, Text, UnstyledButton } from "@mantine/core";
import { IconDeviceDesktop, IconFolders, IconHistory, IconLogout, IconPackage } from "@tabler/icons-react";
import { useMediaQuery } from "@mantine/hooks";
import type { ReactNode } from "react";
import { NavLink as RouterLink, Outlet, useLocation } from "react-router";

import { type Me, api } from "./api";

// Pages to come are shown disabled, with the version that brings them (ROADMAP.md)
const NAV = [
  { to: "/", label: "Machines", icon: IconDeviceDesktop },
  { to: "/packages", label: "Paquets", icon: IconPackage, soon: "v0.3" },
  { to: "/groups", label: "Groupes", icon: IconFolders, soon: "v0.3" },
  { to: "/journal", label: "Journal", icon: IconHistory, soon: "v0.4" },
];

async function logout() {
  await api.post("/auth/logout");
  window.location.assign("/?auth_error=logged_out");
}

export default function Layout({ me }: { me: Me }) {
  const { pathname } = useLocation();
  const phone = useMediaQuery("(max-width: 48em)");
  const active = (to: string) => (to === "/" ? pathname === "/" || pathname.startsWith("/hosts") : pathname.startsWith(to));

  return (
    <AppShell
      header={{ height: 52 }}
      navbar={{ width: 220, breakpoint: "sm", collapsed: { mobile: true } }}
      footer={phone ? { height: 64 } : undefined}
      padding="md"
    >
      <AppShell.Header px="md">
        <Group h="100%" justify="space-between" wrap="nowrap">
          <Group gap="xs" wrap="nowrap">
            <img src="/icon.svg" alt="" width={28} height={28} />
            <Text fw={700}>WAPT Console</Text>
          </Group>
          <Group gap="xs" wrap="nowrap">
            <Text size="sm" c="dimmed" visibleFrom="sm">{me.user.name || me.user.username}</Text>
            <ActionIcon variant="subtle" color="gray" size="lg" aria-label="Se déconnecter" onClick={logout}>
              <IconLogout size={18} />
            </ActionIcon>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="xs">
        {NAV.map(({ to, label, icon: Icon, soon }) => (
          <NavLink key={to} component={RouterLink} to={to} label={label} active={active(to)} disabled={!!soon}
                   description={soon ? `bientôt (${soon})` : undefined} leftSection={<Icon size={18} />} />
        ))}
      </AppShell.Navbar>

      <AppShell.Main>
        <Outlet />
      </AppShell.Main>

      {phone && (
        <AppShell.Footer style={{ paddingBottom: "env(safe-area-inset-bottom)" }}>
          <Group h="100%" grow gap={0}>
            {NAV.map(({ to, label, icon: Icon, soon }) => (
              <BottomTab key={to} to={to} label={label} active={active(to)} disabled={!!soon}
                         icon={<Icon size={22} />} />
            ))}
          </Group>
        </AppShell.Footer>
      )}
    </AppShell>
  );
}

function BottomTab({ to, label, active, disabled, icon }: {
  to: string; label: string; active: boolean; disabled: boolean; icon: ReactNode;
}) {
  return (
    <UnstyledButton component={RouterLink} to={to} h="100%" aria-disabled={disabled}
                    onClick={(e) => disabled && e.preventDefault()}
                    c={active ? "blue" : "dimmed"}
                    style={{ display: "flex", justifyContent: "center", opacity: disabled ? 0.4 : 1 }}>
      <Stack gap={2} align="center" justify="center">
        {icon}
        <Text size="xs" fw={active ? 600 : 400}>{label}</Text>
      </Stack>
    </UnstyledButton>
  );
}
