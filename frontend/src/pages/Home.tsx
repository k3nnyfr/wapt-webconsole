import { Alert, Card, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";

import { type Me, type WaptStatus, api } from "../api";

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <Card withBorder radius="md" padding="md">
      <Text size="sm" c="dimmed">{label}</Text>
      <Text size="xl" fw={700}>{value}</Text>
    </Card>
  );
}

export default function Home({ me }: { me: Me }) {
  const { data, error } = useQuery({
    queryKey: ["wapt-status"],
    queryFn: () => api.get<WaptStatus>("/api/wapt/status"),
    refetchInterval: 30_000,
  });

  return (
    <Stack>
      <Title order={2}>Tableau de bord</Title>
      <Text c="dimmed">
        Serveur {me.wapt_url} · connecté en tant que {me.user.name || me.user.username} ({me.user.role})
      </Text>
      {error && <Alert color="red" title="Serveur WAPT injoignable">{(error as Error).message}</Alert>}
      <SimpleGrid cols={{ base: 2, sm: 3 }}>
        <Stat label="Machines" value={data?.hosts ?? "…"} />
        <Stat label="Connectées" value={data?.connected ?? "…"} />
      </SimpleGrid>
    </Stack>
  );
}
