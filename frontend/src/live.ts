// Live host status over the backend WebSocket (/api/ws): a snapshot, then the changed hosts.
// Reconnects with a growing delay, and at once when the page becomes visible again (phones suspend sockets).

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { type Host, type HostsAnswer, loginUrl } from "./api";

export type LiveState = "connecting" | "live" | "offline";

type Message =
  | { type: "snapshot"; hosts: Host[]; read_at: number }
  | { type: "update"; changed: Host[]; removed: string[]; read_at: number };

export function useLiveHosts(): LiveState {
  const queryClient = useQueryClient();
  const [state, setState] = useState<LiveState>("connecting");

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: number | undefined;
    let delay = 1000;
    let stopped = false;

    const apply = (msg: Message) => {
      queryClient.setQueryData<HostsAnswer>(["hosts"], (old) => {
        if (msg.type === "snapshot") return { hosts: msg.hosts, read_at: msg.read_at, server: old?.server ?? "" };
        if (!old) return old;
        const changed = new Map(msg.changed.map((h) => [h.uuid, h]));
        const removed = new Set(msg.removed);
        const hosts = old.hosts.filter((h) => !removed.has(h.uuid)).map((h) => changed.get(h.uuid) ?? h);
        for (const h of msg.changed) if (!old.hosts.some((o) => o.uuid === h.uuid)) hosts.push(h);
        return { ...old, hosts, read_at: msg.read_at };
      });
    };

    const connect = () => {
      if (stopped) return;
      window.clearTimeout(retry);
      setState("connecting");
      const scheme = window.location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${scheme}://${window.location.host}/api/ws`);
      ws.onopen = () => {
        delay = 1000;
        setState("live");
      };
      ws.onmessage = (e) => apply(JSON.parse(e.data) as Message);
      ws.onclose = (e) => {
        ws = null;
        if (stopped) return;
        if (e.code === 4401) {                       // session expired or missing: log in again
          window.location.assign(loginUrl());
          return;
        }
        setState("offline");
        retry = window.setTimeout(connect, delay);
        delay = Math.min(delay * 2, 30_000);
      };
    };

    const onVisible = () => {
      if (document.visibilityState === "visible" && !ws) {
        delay = 1000;
        connect();
      }
    };

    connect();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stopped = true;
      window.clearTimeout(retry);
      document.removeEventListener("visibilitychange", onVisible);
      ws?.close();
    };
  }, [queryClient]);

  return state;
}
