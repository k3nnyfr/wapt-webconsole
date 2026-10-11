// Display preferences kept in the browser (per user): convenience only, the page works without them
// (private window, blocked storage). Server-side preferences are planned later (ROADMAP.md).

import { useCallback, useState } from "react";

function read<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

export function usePersistentState<T>(key: string, fallback: T, valid: (v: T) => boolean = () => true) {
  const [value, setValue] = useState<T>(() => {
    const stored = read(key, fallback);
    return valid(stored) ? stored : fallback;
  });
  const update = useCallback(
    (next: T) => {
      setValue(next);
      try {
        window.localStorage.setItem(key, JSON.stringify(next));
      } catch {
        // storage unavailable: the choice lasts until the page is reloaded
      }
    },
    [key],
  );
  return [value, update] as const;
}
