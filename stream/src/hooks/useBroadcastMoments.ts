import { useCallback, useEffect, useMemo, useReducer, type Dispatch } from "react";
import type { BroadcastMomentPayload } from "../shared/useLiveEvents";

export const DEFAULT_BROADCAST_MOMENT_LIMIT = 24;

export type BroadcastMoment = BroadcastMomentPayload & {
  receivedAt: number;
  expiresAt: number | null;
  sequence: number;
};

export type BroadcastMomentAction =
  | {
      type: "add";
      moment: BroadcastMomentPayload;
      limit?: number;
      receivedAt?: number | string;
    }
  | { type: "clear" }
  | { type: "pruneExpired"; now?: number }
  | { type: "resize"; limit?: number };

export type BroadcastMomentState = {
  moments: BroadcastMoment[];
  nextSequence: number;
};

export type UseBroadcastMomentsOptions = {
  limit?: number;
};

export type UseBroadcastMomentsResult = {
  moments: BroadcastMoment[];
  priorityMoments: BroadcastMoment[];
  addMoment: (moment: BroadcastMomentPayload, receivedAt?: number | string) => void;
  clearMoments: () => void;
  pruneExpired: (now?: number) => void;
  dispatch: Dispatch<BroadcastMomentAction>;
};

const INITIAL_STATE: BroadcastMomentState = {
  moments: [],
  nextSequence: 0,
};

function normalizeLimit(limit?: number): number {
  if (!Number.isFinite(limit) || limit == null) return DEFAULT_BROADCAST_MOMENT_LIMIT;
  return Math.max(1, Math.floor(limit));
}

function toEpochMs(value: number | string | undefined, fallback: number): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

function createBufferedMoment(
  moment: BroadcastMomentPayload,
  sequence: number,
  receivedAtInput?: number | string,
): BroadcastMoment {
  const receivedAt = toEpochMs(receivedAtInput, toEpochMs(moment.created_at, Date.now()));
  const ttlMs = Number.isFinite(moment.ttl_sec) ? Math.max(0, moment.ttl_sec) * 1_000 : 0;

  return {
    ...moment,
    receivedAt,
    expiresAt: ttlMs > 0 ? receivedAt + ttlMs : null,
    sequence,
  };
}

export function trimBroadcastMomentFifo<T>(
  moments: readonly T[],
  limit = DEFAULT_BROADCAST_MOMENT_LIMIT,
): T[] {
  const max = normalizeLimit(limit);
  return moments.slice(Math.max(0, moments.length - max));
}

export function sortBroadcastMomentsByPriority(
  moments: readonly BroadcastMoment[],
): BroadcastMoment[] {
  return [...moments].sort((a, b) => {
    if (a.priority !== b.priority) return b.priority - a.priority;
    if (a.receivedAt !== b.receivedAt) return b.receivedAt - a.receivedAt;
    return b.sequence - a.sequence;
  });
}

export function broadcastMomentReducer(
  state: BroadcastMomentState,
  action: BroadcastMomentAction,
): BroadcastMomentState {
  switch (action.type) {
    case "add": {
      const buffered = createBufferedMoment(
        action.moment,
        state.nextSequence,
        action.receivedAt,
      );
      const deduped = state.moments.filter((moment) => moment.id !== buffered.id);
      return {
        moments: trimBroadcastMomentFifo([...deduped, buffered], action.limit),
        nextSequence: state.nextSequence + 1,
      };
    }
    case "clear":
      return { moments: [], nextSequence: state.nextSequence };
    case "pruneExpired": {
      const now = action.now ?? Date.now();
      return {
        ...state,
        moments: state.moments.filter(
          (moment) => moment.expiresAt == null || moment.expiresAt > now,
        ),
      };
    }
    case "resize":
      return {
        ...state,
        moments: trimBroadcastMomentFifo(state.moments, action.limit),
      };
  }
}

export function useBroadcastMoments(
  options: UseBroadcastMomentsOptions = {},
): UseBroadcastMomentsResult {
  const limit = normalizeLimit(options.limit);
  const [state, dispatch] = useReducer(broadcastMomentReducer, INITIAL_STATE);

  useEffect(() => {
    dispatch({ type: "resize", limit });
  }, [limit]);

  const addMoment = useCallback(
    (moment: BroadcastMomentPayload, receivedAt?: number | string) => {
      dispatch({ type: "add", moment, receivedAt, limit });
    },
    [limit],
  );

  const clearMoments = useCallback(() => {
    dispatch({ type: "clear" });
  }, []);

  const pruneExpired = useCallback((now?: number) => {
    dispatch({ type: "pruneExpired", now });
  }, []);

  const priorityMoments = useMemo(
    () => sortBroadcastMomentsByPriority(state.moments),
    [state.moments],
  );

  return {
    moments: state.moments,
    priorityMoments,
    addMoment,
    clearMoments,
    pruneExpired,
    dispatch,
  };
}
