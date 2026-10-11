// Choice and order of the host columns: popover on a computer, bottom sheet on a phone.

import { ActionIcon, Button, Checkbox, Divider, Drawer, Group, Popover, ScrollArea, Stack, Text } from "@mantine/core";
import { useDisclosure, useMediaQuery } from "@mantine/hooks";
import { IconArrowDown, IconArrowUp, IconColumns } from "@tabler/icons-react";

import { COLUMNS, COLUMN_BY_ID, DEFAULT_COLUMNS } from "./columns";

interface Props {
  visible: string[];
  onChange: (columns: string[]) => void;
}

function Picker({ visible, onChange }: Props) {
  const move = (id: string, delta: number) => {
    const i = visible.indexOf(id);
    const j = i + delta;
    if (j < 0 || j >= visible.length) return;
    const next = [...visible];
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  };
  const toggle = (id: string, on: boolean) =>
    onChange(on ? [...visible, id] : visible.filter((c) => c !== id || visible.length === 1));
  const hidden = COLUMNS.filter((c) => !visible.includes(c.id));
  const groups = [...new Set(hidden.map((c) => c.group))];

  return (
    <Stack gap="xs">
      <Text size="xs" fw={700} c="dimmed" tt="uppercase">Affichées, dans l'ordre</Text>
      {visible.map((id, i) => (
        <Group key={id} justify="space-between" wrap="nowrap" gap="xs">
          <Checkbox label={COLUMN_BY_ID[id]?.label ?? id} checked onChange={() => toggle(id, false)}
                    disabled={visible.length === 1} />
          <Group gap={2} wrap="nowrap">
            <ActionIcon variant="subtle" color="gray" size="md" disabled={i === 0} onClick={() => move(id, -1)}
                        aria-label="Monter"><IconArrowUp size={16} /></ActionIcon>
            <ActionIcon variant="subtle" color="gray" size="md" disabled={i === visible.length - 1}
                        onClick={() => move(id, 1)} aria-label="Descendre"><IconArrowDown size={16} /></ActionIcon>
          </Group>
        </Group>
      ))}
      {groups.map((g) => (
        <Stack key={g} gap={6}>
          <Divider label={g} labelPosition="left" />
          {hidden.filter((c) => c.group === g).map((c) => (
            <Checkbox key={c.id} label={c.label} checked={false} onChange={() => toggle(c.id, true)} />
          ))}
        </Stack>
      ))}
      <Button variant="subtle" size="xs" onClick={() => onChange(DEFAULT_COLUMNS)}>
        Colonnes par défaut
      </Button>
    </Stack>
  );
}

export default function ColumnsPicker(props: Props) {
  const phone = useMediaQuery("(max-width: 48em)");
  const [opened, { open, close, toggle }] = useDisclosure(false);
  const trigger = (
    <Button variant="default" leftSection={<IconColumns size={16} />} onClick={phone ? open : toggle}>
      Colonnes
    </Button>
  );
  if (phone) {
    return (
      <>
        {trigger}
        <Drawer opened={opened} onClose={close} position="bottom" size="85%" title="Colonnes" radius="md">
          <Picker {...props} />
        </Drawer>
      </>
    );
  }
  return (
    <Popover opened={opened} onChange={(o) => !o && close()} position="bottom-end" shadow="md" width={300}>
      <Popover.Target>{trigger}</Popover.Target>
      <Popover.Dropdown p="sm">
        <ScrollArea.Autosize mah="70vh" type="auto" offsetScrollbars>
          <Picker {...props} />
        </ScrollArea.Autosize>
      </Popover.Dropdown>
    </Popover>
  );
}
