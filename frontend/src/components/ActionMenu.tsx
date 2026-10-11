// One action menu for every support: right click and ⋮ button on a computer, long press and ⋮ on a touch screen.
// On a phone it is shown as a bottom sheet (Drawer), elsewhere as a menu at the pointer position.

import { Drawer, Menu, NavLink, Stack, Text } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import {
  createContext,
  type MouseEvent,
  type PointerEvent,
  type ReactNode,
  useCallback,
  useContext,
  useRef,
  useState,
} from "react";

export interface Action {
  key: string;
  label: string;
  icon?: ReactNode;
  color?: string;
  disabled?: boolean;
  hint?: string; // shown next to a disabled action, e.g. the version that brings it
  onClick?: () => void;
}

interface MenuState {
  title: string;
  actions: Action[];
  x: number;
  y: number;
}

const LONG_PRESS_MS = 500;
const MOVE_TOLERANCE = 10;

const OpenMenu = createContext<(state: MenuState) => void>(() => {});

export function ActionMenuProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<MenuState | null>(null);
  const phone = useMediaQuery("(max-width: 48em)");
  const close = () => setState(null);
  const run = (action: Action) => {
    close();
    action.onClick?.();
  };

  return (
    <OpenMenu.Provider value={setState}>
      {children}
      {phone ? (
        <Drawer opened={state !== null} onClose={close} position="bottom" size="auto" title={state?.title}
                radius="md" padding="md">
          <Stack gap={4} pb="md">
            {state?.actions.map((a) => (
              <NavLink key={a.key} label={a.label} leftSection={a.icon} color={a.color} disabled={a.disabled}
                       description={a.disabled ? a.hint : undefined} onClick={() => run(a)}
                       style={{ minHeight: 48, borderRadius: 8 }} />
            ))}
          </Stack>
        </Drawer>
      ) : (
        <Menu opened={state !== null} onChange={(o) => !o && close()} position="bottom-start" shadow="md"
              width={260} withinPortal>
          <Menu.Target>
            <div style={{ position: "fixed", left: state?.x ?? 0, top: state?.y ?? 0, width: 1, height: 1 }} />
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Label>{state?.title}</Menu.Label>
            {state?.actions.map((a) => (
              <Menu.Item key={a.key} leftSection={a.icon} color={a.color} disabled={a.disabled}
                         rightSection={a.disabled && a.hint ? <Text size="xs" c="dimmed">{a.hint}</Text> : null}
                         onClick={() => run(a)}>
                {a.label}
              </Menu.Item>
            ))}
          </Menu.Dropdown>
        </Menu>
      )}
    </OpenMenu.Provider>
  );
}

/** Props to spread on an element (row, card) so that its menu opens on right click or long press. */
export function useActionMenu() {
  const open = useContext(OpenMenu);
  const timer = useRef<number | undefined>(undefined);
  const start = useRef<{ x: number; y: number } | null>(null);
  const opened = useRef(false);

  const cancel = () => {
    window.clearTimeout(timer.current);
    start.current = null;
  };

  const bind = useCallback(
    (title: string, actions: Action[]) => ({
      // Right click, and long press on Android Chrome, which fires contextmenu itself
      onContextMenu: (e: MouseEvent) => {
        e.preventDefault();
        cancel();
        opened.current = true;
        open({ title, actions, x: e.clientX, y: e.clientY });
      },
      // Fallback for touch browsers that do not fire contextmenu on long press
      onPointerDown: (e: PointerEvent) => {
        if (e.pointerType !== "touch") return;
        opened.current = false;
        start.current = { x: e.clientX, y: e.clientY };
        const { clientX: x, clientY: y } = e;
        timer.current = window.setTimeout(() => {
          if (!opened.current) open({ title, actions, x, y });
          opened.current = true;
        }, LONG_PRESS_MS);
      },
      onPointerMove: (e: PointerEvent) => {
        const s = start.current;
        if (s && Math.hypot(e.clientX - s.x, e.clientY - s.y) > MOVE_TOLERANCE) cancel(); // scrolling
      },
      onPointerUp: cancel,
      onPointerCancel: cancel,
      // A long press must not also trigger the element's click
      onClickCapture: (e: MouseEvent) => {
        if (opened.current) {
          e.stopPropagation();
          opened.current = false;
        }
      },
    }),
    [open],
  );

  /** For the ⋮ button: menu under the button. */
  const openFrom = useCallback(
    (e: MouseEvent<HTMLElement>, title: string, actions: Action[]) => {
      e.stopPropagation();
      const r = e.currentTarget.getBoundingClientRect();
      open({ title, actions, x: r.left, y: r.bottom });
    },
    [open],
  );

  return { bind, openFrom };
}
