// Small focus-trap helper for modal dialogs. On mount, focuses the first
// focusable descendant (or the dialog itself if none). Tab/Shift+Tab at the
// edges cycle within the container. On unmount, returns focus to whatever
// had focus before the dialog opened (typically the trigger button).
//
// Kept dependency-free and side-effect-only so it composes with the modal
// `useEffect`s without any state churn.

import { useEffect, useRef, type RefObject } from "react";

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

function getFocusable(container: HTMLElement): HTMLElement[] {
  const nodes = Array.from(
    container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
  );
  return nodes.filter(
    (n) => !n.hasAttribute("disabled") && n.tabIndex !== -1 && isVisible(n),
  );
}

function isVisible(n: HTMLElement): boolean {
  // Skip elements that are display:none or hidden via the HTML `hidden` attr.
  if (n.hidden) return false;
  const style = typeof window !== "undefined" ? window.getComputedStyle(n) : null;
  if (style && (style.display === "none" || style.visibility === "hidden")) {
    return false;
  }
  return true;
}

export function useFocusTrap<T extends HTMLElement>(
  active: boolean,
): RefObject<T | null> {
  const ref = useRef<T | null>(null);

  useEffect(() => {
    if (!active) return;
    const container = ref.current;
    if (!container) return;

    const previouslyFocused = document.activeElement as HTMLElement | null;

    // Defer to next frame so the dialog's children are mounted (some
    // consumers render loading/error states first).
    const raf = requestAnimationFrame(() => {
      const focusables = getFocusable(container);
      const target = focusables[0] ?? container;
      if (typeof target.focus === "function") target.focus();
    });

    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const focusables = getFocusable(container);
      if (focusables.length === 0) {
        // Nothing to cycle; keep focus on the container itself.
        e.preventDefault();
        if (typeof container.focus === "function") container.focus();
        return;
      }
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const current = document.activeElement as HTMLElement | null;
      if (e.shiftKey) {
        if (current === first || !container.contains(current)) {
          e.preventDefault();
          last?.focus();
        }
      } else {
        if (current === last || !container.contains(current)) {
          e.preventDefault();
          first?.focus();
        }
      }
    };

    document.addEventListener("keydown", onKey, true);

    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("keydown", onKey, true);
      // Return focus to the trigger on close. Skip if the trigger is gone
      // (e.g. parent unmounted) or if focus has already moved elsewhere.
      if (
        previouslyFocused &&
        typeof previouslyFocused.focus === "function" &&
        document.contains(previouslyFocused)
      ) {
        previouslyFocused.focus();
      }
    };
  }, [active]);

  return ref;
}
