// Host filters by value (system, state, audit, domain, agent): popover on a computer, bottom sheet on a phone,
// active values shown as removable badges.

import { Badge, Button, CloseButton, Drawer, Group, MultiSelect, Popover, Stack } from "@mantine/core";
import { useDisclosure, useMediaQuery } from "@mantine/hooks";
import { IconFilter } from "@tabler/icons-react";

import type { Host } from "../api";

export const FILTERS = [
  { id: "os_name", label: "Système" },
  { id: "status", label: "État" },
  { id: "audit_status", label: "Audit" },
  { id: "dnsdomain", label: "Domaine" },
  { id: "wapt_version", label: "Agent" },
] as const;

export type FilterId = (typeof FILTERS)[number]["id"];
export type FilterValues = Partial<Record<FilterId, string[]>>;

export function matchesFilters(h: Host, filters: FilterValues): boolean {
  return FILTERS.every(({ id }) => !filters[id]?.length || filters[id]!.includes(h[id] || "(vide)"));
}

function options(hosts: Host[], id: FilterId): string[] {
  return [...new Set(hosts.map((h) => h[id] || "(vide)"))].sort((a, b) => a.localeCompare(b, "fr"));
}

export function ActiveFilters({ filters, onChange }: { filters: FilterValues; onChange: (f: FilterValues) => void }) {
  const active = FILTERS.flatMap(({ id, label }) => (filters[id] ?? []).map((v) => ({ id, label, v })));
  if (!active.length) return null;
  return (
    <Group gap={6}>
      {active.map(({ id, label, v }) => (
        <Badge key={`${id}-${v}`} variant="light" tt="none" pr={3}
               rightSection={<CloseButton size="xs" aria-label="Retirer"
                 onClick={() => onChange({ ...filters, [id]: filters[id]!.filter((x) => x !== v) })} />}>
          {label} : {v}
        </Badge>
      ))}
      <Button variant="subtle" size="compact-xs" onClick={() => onChange({})}>Tout effacer</Button>
    </Group>
  );
}

export default function Filters({ hosts, filters, onChange }: {
  hosts: Host[]; filters: FilterValues; onChange: (f: FilterValues) => void;
}) {
  const phone = useMediaQuery("(max-width: 48em)");
  const [opened, { open, close, toggle }] = useDisclosure(false);
  const count = Object.values(filters).reduce((n, v) => n + (v?.length ?? 0), 0);
  const content = (
    <Stack gap="sm">
      {FILTERS.map(({ id, label }) => (
        <MultiSelect key={id} label={label} data={options(hosts, id)} value={filters[id] ?? []} searchable
                     clearable onChange={(v) => onChange({ ...filters, [id]: v })} comboboxProps={{ withinPortal: false }} />
      ))}
    </Stack>
  );
  const trigger = (
    <Button variant={count ? "light" : "default"} leftSection={<IconFilter size={16} />} size={phone ? "md" : "sm"}
            onClick={phone ? open : toggle}>
      Filtres{count ? ` (${count})` : ""}
    </Button>
  );
  if (phone) {
    return (
      <>
        {trigger}
        <Drawer opened={opened} onClose={close} position="bottom" size="auto" title="Filtres" radius="md">
          <Stack pb="md">{content}<Button onClick={close}>Voir les machines</Button></Stack>
        </Drawer>
      </>
    );
  }
  return (
    <Popover opened={opened} onChange={(o) => !o && close()} position="bottom-end" shadow="md" width={320}>
      <Popover.Target>{trigger}</Popover.Target>
      <Popover.Dropdown>{content}</Popover.Dropdown>
    </Popover>
  );
}
