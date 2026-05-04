import { useCallback, useState } from "react";

const NS = "tradefarm.dashboard.tabs";

function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(`${NS}.${key}`);
  } catch {
    return null;
  }
}

function writeStored(key: string, value: string): void {
  try {
    window.localStorage.setItem(`${NS}.${key}`, value);
  } catch {
    /* localStorage unavailable / quota / private mode — ignore */
  }
}

export function usePersistedTab(
  key: string,
  defaultId: string,
): [string, (id: string) => void] {
  const [id, setId] = useState<string>(() => readStored(key) ?? defaultId);

  const setPersisted = useCallback(
    (next: string) => {
      setId(next);
      writeStored(key, next);
    },
    [key],
  );

  return [id, setPersisted];
}
