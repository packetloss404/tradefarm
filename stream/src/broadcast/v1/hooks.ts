import { useEffect, useRef, useState } from "react";

/**
 * Smoothly interpolate from the previous value to `target` over `ms` using a
 * cubic-out ease. Mirrors the design's `useAnimatedNumber` for scoreboard
 * values and race-lane progress.
 */
export function useAnimatedNumber(target: number, ms = 350): number {
  const [val, setVal] = useState<number>(target);
  const ref = useRef<{ from: number; to: number; t0: number }>({
    from: target,
    to: target,
    t0: 0,
  });

  useEffect(() => {
    ref.current = { from: val, to: target, t0: performance.now() };
    let raf = 0;
    const step = () => {
      const { from, to, t0 } = ref.current;
      const p = Math.min(1, (performance.now() - t0) / ms);
      const eased = 1 - Math.pow(1 - p, 3);
      setVal(from + (to - from) * eased);
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
    // The animation should restart whenever `target` changes; reading `val`
    // here as a starting point is intentional and reading-only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, ms]);

  return val;
}

/**
 * Returns `true` for ~`ms` after `dep` changes, then `false`. Used for the
 * scoreboard's text-shadow flash on every tick.
 */
export function useTickPulse(dep: number | string, ms = 250): boolean {
  const [pulse, setPulse] = useState<boolean>(false);
  useEffect(() => {
    setPulse(true);
    const t = setTimeout(() => setPulse(false), ms);
    return () => clearTimeout(t);
  }, [dep, ms]);
  return pulse;
}

/**
 * Wall-clock state, refreshed every `intervalMs`. Used by the ET clock.
 */
export function useNow(intervalMs = 500): Date {
  const [now, setNow] = useState<Date>(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
