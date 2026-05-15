import { useEffect, useRef, useState } from "react";

const STREAM_VITE_PORT = 5180;
const POPUP_NAME = "tradefarm-stream-preview";
const POPUP_W = 1280;
const POPUP_H = 720;

function streamUrl(): string {
  // Dev convention: stream Vite serves at :5180 on the same host as the
  // dashboard (:5179). Same machine in practice — second monitor or a popup.
  const host = typeof location !== "undefined" ? location.hostname : "localhost";
  const scheme = typeof location !== "undefined" && location.protocol === "https:" ? "https:" : "http:";
  return `${scheme}//${host}:${STREAM_VITE_PORT}`;
}

export function PreviewPopoutButton() {
  const winRef = useRef<Window | null>(null);
  const [open, setOpen] = useState(false);

  // Poll the popup ref so the button's "open"/"closed" state stays honest
  // when the operator closes the window directly.
  useEffect(() => {
    if (!open) return;
    const t = setInterval(() => {
      if (winRef.current?.closed) {
        winRef.current = null;
        setOpen(false);
      }
    }, 1000);
    return () => clearInterval(t);
  }, [open]);

  const onClick = () => {
    if (winRef.current && !winRef.current.closed) {
      winRef.current.focus();
      return;
    }
    const features = `popup,width=${POPUP_W},height=${POPUP_H},menubar=no,toolbar=no,location=no,status=no,resizable=yes`;
    const w = window.open(streamUrl(), POPUP_NAME, features);
    if (w) {
      winRef.current = w;
      setOpen(true);
    }
  };

  return (
    <button
      onClick={onClick}
      title={`Pop out a 1280×720 preview of the stream (${streamUrl()})`}
      className={`flex items-center gap-1.5 rounded-sm border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider transition-colors ${
        open
          ? "border-(--color-profit)/60 bg-(--color-profit)/10 text-(--color-profit) hover:bg-(--color-profit)/20"
          : "border-zinc-700 bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
      }`}
    >
      <span aria-hidden>{open ? "◉" : "↗"}</span>
      <span>{open ? "Preview live" : "Pop out preview"}</span>
    </button>
  );
}
