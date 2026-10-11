// Package or group detail: description, content, versions in the repository, hosts where it is deployed.

import { Alert, Anchor, Badge, Card, Drawer, Group, Loader, ScrollArea, Stack, Table, Text, Title,
  UnstyledButton } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useNavigate } from "react-router";

import { type PackageDetail as Detail, api } from "../api";
import { RelativeDate, StatusBadge } from "../hosts/columns";
import { PackageIcon, formatSize } from "./common";

function Field({ label, children }: { label: string; children: ReactNode }) {
  if (!children) return null;
  return (
    <Group gap="xs" wrap="nowrap" align="flex-start">
      <Text size="sm" c="dimmed" w={130} style={{ flexShrink: 0 }}>{label}</Text>
      <Text size="sm" component="div" style={{ wordBreak: "break-word" }}>{children}</Text>
    </Group>
  );
}

export default function PackageDetail({ name, base, onClose }: {
  name: string | undefined; base: "/packages" | "/groups"; onClose: () => void;
}) {
  const phone = useMediaQuery("(max-width: 48em)");
  const navigate = useNavigate();
  const { data, error, isLoading } = useQuery({
    queryKey: ["package", name],
    queryFn: () => api.get<Detail>(`/api/packages/${encodeURIComponent(name!)}`),
    enabled: !!name,
  });
  const p = data?.package;
  const group = p?.section === "group";

  return (
    <Drawer opened={!!name} onClose={onClose} position="right" size={phone ? "100%" : "min(860px, 70%)"}
            padding="md" scrollAreaComponent={ScrollArea.Autosize}
            title={<Group gap="sm" wrap="nowrap">
              {p && <PackageIcon icon={p.icon} group={group} size={40} />}
              <Stack gap={0}>
                <Title order={3}>{p?.name || name}</Title>
                {p && <Text size="sm" c="dimmed">{p.package} · {p.version}</Text>}
              </Stack>
            </Group>}>
      {isLoading && <Loader />}
      {error && <Alert color="red" title="Paquet indisponible">{(error as Error).message}</Alert>}
      {p && data && (
        <Stack gap="md">
          {p.description && <Text size="sm">{p.description}</Text>}
          <Card withBorder radius="md" padding="sm">
            <Stack gap={6}>
              <Field label="Éditeur">{p.editor}</Field>
              <Field label="Licence">{p.licence}</Field>
              <Field label="Catégories">{p.categories.join(", ")}</Field>
              <Field label="Système">{[p.target_os, p.architecture].filter(Boolean).join(" · ")}</Field>
              <Field label="Maturité">{p.maturity}</Field>
              <Field label="Langue">{p.locale}</Field>
              <Field label="Taille">{formatSize(p.size)}</Field>
              <Field label="Signé par">{p.signer}</Field>
              <Field label="Signé">{p.signature_date && <RelativeDate iso={p.signature_date} />}</Field>
              <Field label="Site">{p.homepage &&
                <Anchor href={p.homepage} target="_blank" rel="noopener noreferrer" size="sm">{p.homepage}</Anchor>}</Field>
            </Stack>
          </Card>

          {(p.depends.length > 0 || group) && (
            <Stack gap={6}>
              <Text fw={600} size="sm">{group ? "Contenu du groupe" : "Dépendances"} ({p.depends.length})</Text>
              <Group gap={6}>
                {p.depends.map((d) => (
                  <Badge key={d} variant="light" tt="none" style={{ cursor: "pointer" }}
                         onClick={() => navigate(`/packages/${encodeURIComponent(d)}`)}>{d}</Badge>
                ))}
              </Group>
            </Stack>
          )}
          {p.conflicts.length > 0 && (
            <Stack gap={6}>
              <Text fw={600} size="sm">Conflits</Text>
              <Group gap={6}>{p.conflicts.map((c) => <Badge key={c} color="red" variant="light" tt="none">{c}</Badge>)}</Group>
            </Stack>
          )}

          <Stack gap={6}>
            <Text fw={600} size="sm">Machines ({data.hosts.length})</Text>
            {data.hosts.length === 0 && <Text size="sm" c="dimmed">Aucune machine.</Text>}
            {data.hosts.map((h) => (
              <UnstyledButton key={h.uuid} onClick={() => navigate(`/hosts/${h.uuid}`)}>
                <Card withBorder radius="sm" padding="xs">
                  <Group justify="space-between" wrap="nowrap">
                    <Stack gap={0} style={{ minWidth: 0 }}>
                      <Text size="sm" fw={500} truncate>{h.name}</Text>
                      <Text size="xs" c="dimmed">{h.version}</Text>
                    </Stack>
                    <Group gap={4} wrap="nowrap">
                      {h.audit_status && h.audit_status !== "OK" && <StatusBadge value={h.audit_status} />}
                      <StatusBadge value={h.install_status} />
                    </Group>
                  </Group>
                </Card>
              </UnstyledButton>
            ))}
          </Stack>

          {data.versions.length > 1 && (
            <Stack gap={6}>
              <Text fw={600} size="sm">Versions dans le dépôt ({data.versions.length})</Text>
              <Table fz="sm" verticalSpacing={4}>
                <Table.Tbody>
                  {data.versions.map((v) => (
                    <Table.Tr key={v.filename || v.version}>
                      <Table.Td>{v.version}</Table.Td>
                      <Table.Td>{[v.target_os, v.architecture, v.maturity].filter(Boolean).join(" · ")}</Table.Td>
                      <Table.Td>{v.signature_date && <RelativeDate iso={v.signature_date} />}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Stack>
          )}
          <Text size="xs" c="dimmed">
            {base === "/groups" ? "Création et modification des groupes : v0.5." : "Suppression et nettoyage du dépôt : v0.6."}
          </Text>
        </Stack>
      )}
    </Drawer>
  );
}
