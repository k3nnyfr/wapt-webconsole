import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";

import { Alert, Button, Center, Loader, MantineProvider, Stack, createTheme } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { StrictMode, useMemo } from "react";
import { createRoot } from "react-dom/client";
import { Navigate, RouterProvider, createBrowserRouter } from "react-router";

import Layout from "./Layout";
import { type Me, api, authError, loginUrl, setCsrfToken } from "./api";
import { ActionMenuProvider } from "./components/ActionMenu";
import HostsPage from "./hosts/HostsPage";
import JournalPage from "./journal/JournalPage";
import { ActionsProvider } from "./ops/actions";
import { AssignProvider } from "./ops/assign";
import { SigningProvider } from "./ops/signing";
import RepoPage from "./repo/RepoPage";

const theme = createTheme({ primaryColor: "blue", defaultRadius: "md" });
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true } } });

const AUTH_MESSAGES: Record<string, string> = {
  forbidden: "Votre compte n'appartient à aucun groupe autorisé à utiliser la console.",
  callback: "La connexion a échoué. Réessayez.",
  logged_out: "Vous êtes déconnecté.",
};

function AuthMessage({ code }: { code: string }) {
  return (
    <Center h="100vh" p="md">
      <Stack maw={420}>
        <Alert color={code === "logged_out" ? "blue" : "red"} title="WAPT Console">
          {AUTH_MESSAGES[code] ?? "Connexion impossible."}
        </Alert>
        <Button component="a" href={loginUrl()}>Se connecter</Button>
      </Stack>
    </Center>
  );
}

function App() {
  const { data: me, error } = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      const me = await api.get<Me>("/api/me");
      setCsrfToken(me.csrf);
      return me;
    },
    retry: false,
    staleTime: Infinity, // identity and CSRF token for the whole session: a refetch would rebuild the router
  });
  const router = useMemo(
    () =>
      me &&
      createBrowserRouter([
        {
          element: <Layout me={me} />,
          children: [
            // the host detail is a child route: the hosts page stays mounted (search, filters) while it is open
            { path: "/", element: <HostsPage me={me} />, children: [{ path: "hosts/:uuid", element: null }] },
            { path: "/packages", element: <RepoPage kind="package" me={me} />, children: [{ path: ":name", element: null }] },
            { path: "/groups", element: <RepoPage kind="group" me={me} />, children: [{ path: ":name", element: null }] },
            { path: "/journal", element: <JournalPage /> },
            { path: "*", element: <Navigate to="/" replace /> },
          ],
        },
      ]),
    [me],
  );
  if (authError && !me) return <AuthMessage code={authError} />;
  if (error) return <AuthMessage code="callback" />;
  if (!router) return <Center h="100vh"><Loader /></Center>;
  return (
    <SigningProvider me={me!}>
      <AssignProvider>
        <ActionsProvider>
          <RouterProvider router={router} />
        </ActionsProvider>
      </AssignProvider>
    </SigningProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="auto">
      <Notifications position="top-center" />
      <QueryClientProvider client={queryClient}>
        <ActionMenuProvider>
          <App />
        </ActionMenuProvider>
      </QueryClientProvider>
    </MantineProvider>
  </StrictMode>,
);
