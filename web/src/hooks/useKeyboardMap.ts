import { useEffect, useState } from "react";

export type UseKeyboardMap = {
  open: boolean;
  setOpen: (v: boolean) => void;
};

type Options = {
  disabled?: boolean;
};

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

export function useKeyboardMap({ disabled = false }: Options = {}): UseKeyboardMap {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && open) {
        setOpen(false);
        return;
      }
      if (disabled) return;
      if (e.key !== "?") return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (isEditableTarget(e.target)) return;
      e.preventDefault();
      setOpen((prev) => !prev);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, disabled]);

  return { open, setOpen };
}
