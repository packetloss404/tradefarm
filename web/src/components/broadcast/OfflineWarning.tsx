// Warning banner shown at the top of the Broadcast panel when the stream
// app's heartbeat goes stale. Tells the operator that controls will still
// fire but the stream may not respond until it reconnects. The buttons
// stay clickable — the backend's command queue handles offline gracefully
// and surfaces errors via the per-section error displays.

export function OfflineWarning() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="rounded-md border border-amber-700/50 bg-amber-950/40 px-3 py-2 text-xs text-amber-200"
    >
      <span className="font-semibold uppercase tracking-wider text-amber-300">
        Stream offline
      </span>
      <span className="ml-2 text-amber-200/80">
        — controls will be sent when it reconnects.
      </span>
    </div>
  );
}
