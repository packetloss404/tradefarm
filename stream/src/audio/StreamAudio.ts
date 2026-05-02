// Web Audio engine for the stream app.
//
// All sounds are synthesized from oscillators — no samples, no network. This
// keeps the bundle small and lets the audio system work offline.
//
// Browsers (and the Tauri webview) require a user gesture before an
// AudioContext can leave the "suspended" state. `primeOnUserGesture()`
// installs a one-shot pointer/key listener that resumes the context the
// first time the user moves the mouse or hits a key. Until then, calls to
// playKick/playFill/playStinger are silently dropped.

type Direction = "promotion" | "demotion";

const PENTATONIC_C = [0, 2, 4, 7, 9]; // C, D, E, G, A relative to octave root

function midiToFreq(midi: number): number {
  return 440 * Math.pow(2, (midi - 69) / 12);
}

function hashSymbol(symbol: string): number {
  let h = 0;
  for (let i = 0; i < symbol.length; i++) {
    h = (h * 31 + symbol.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

class StreamAudio {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private enabled = true;
  private volume = 0.6;
  private primed = false;

  setEnabled(v: boolean): void {
    this.enabled = v;
  }

  setVolume(v: number): void {
    this.volume = Math.max(0, Math.min(1, v));
    if (this.master) this.master.gain.value = this.volume;
  }

  primeOnUserGesture(): void {
    if (this.primed || typeof window === "undefined") return;
    this.primed = true;
    const handler = () => {
      window.removeEventListener("pointerdown", handler);
      window.removeEventListener("keydown", handler);
      const ctx = this.ensureCtx();
      if (ctx && ctx.state === "suspended") {
        void ctx.resume();
      }
    };
    window.addEventListener("pointerdown", handler);
    window.addEventListener("keydown", handler);
  }

  playKick(): void {
    const ctx = this.ready();
    if (!ctx || !this.master) return;
    const now = ctx.currentTime;

    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(110, now);
    osc.frequency.exponentialRampToValueAtTime(45, now + 0.12);

    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(0.7, now + 0.005);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.28);

    osc.connect(gain).connect(this.master);
    osc.start(now);
    osc.stop(now + 0.32);
  }

  playFill(symbol: string, side: "buy" | "sell", _qty: number): void {
    const ctx = this.ready();
    if (!ctx || !this.master) return;
    const now = ctx.currentTime;

    const noteIdx = hashSymbol(symbol) % PENTATONIC_C.length;
    const note = PENTATONIC_C[noteIdx] ?? 0;
    const baseOctave = side === "buy" ? 5 : 4;
    const midi = 12 * (baseOctave + 1) + note;
    const freq = midiToFreq(midi);

    const osc1 = ctx.createOscillator();
    const osc2 = ctx.createOscillator();
    const overtoneGain = ctx.createGain();
    const gain = ctx.createGain();

    osc1.type = "sine";
    osc1.frequency.value = freq;
    osc2.type = "triangle";
    osc2.frequency.value = freq * 2;
    osc2.detune.value = 5;
    overtoneGain.gain.value = 0.22;

    osc2.connect(overtoneGain).connect(gain);
    osc1.connect(gain);

    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(0.4, now + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.6);

    gain.connect(this.master);

    osc1.start(now);
    osc2.start(now);
    osc1.stop(now + 0.65);
    osc2.stop(now + 0.65);
  }

  playStinger(direction: Direction): void {
    const ctx = this.ready();
    if (!ctx || !this.master) return;
    const now = ctx.currentTime;

    // Promotion: ascending C major → octave-up. Demotion: descending.
    const notes = direction === "promotion" ? [60, 64, 67, 72] : [67, 64, 60, 55];
    notes.forEach((midi, i) => {
      const t0 = now + i * 0.12;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "triangle";
      osc.frequency.value = midiToFreq(midi);
      gain.gain.setValueAtTime(0, t0);
      gain.gain.linearRampToValueAtTime(0.32, t0 + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.001, t0 + 0.5);
      osc.connect(gain).connect(this.master!);
      osc.start(t0);
      osc.stop(t0 + 0.55);
    });
  }

  private ready(): AudioContext | null {
    if (!this.enabled) return null;
    const ctx = this.ensureCtx();
    if (!ctx || ctx.state !== "running") return null;
    return ctx;
  }

  private ensureCtx(): AudioContext | null {
    if (typeof window === "undefined") return null;
    if (this.ctx) return this.ctx;
    type Ctor = typeof AudioContext;
    type W = { AudioContext?: Ctor; webkitAudioContext?: Ctor };
    const w = window as unknown as W;
    const C = w.AudioContext ?? w.webkitAudioContext;
    if (!C) return null;
    try {
      this.ctx = new C();
      this.master = this.ctx.createGain();
      this.master.gain.value = this.volume;
      this.master.connect(this.ctx.destination);
    } catch {
      return null;
    }
    return this.ctx;
  }
}

export const streamAudio = new StreamAudio();
