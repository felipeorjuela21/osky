/* Listening with Silero VAD (a small neural network running in the browser, free).

   It tells real speech from noise far better than a loudness threshold, so Osky
   knows sooner and more reliably when you finished talking. It also listens while
   Osky speaks: if you talk over him for a moment he stops and listens (barge-in).

   On iPhone/iPad the microphone is only open while it's your turn, as before:
   with the mic open, iOS plays Osky through the quiet earpiece.

   If the detector can't load (old browser, files missing) PersonaView falls back
   to the loudness-based listening in stt.ts. */

import type { MicVAD } from "@ricky0123/vad-web";
import type { ListenHandle } from "./speech";
import { ListenPhase, openMic, transcribeOnServer } from "./stt";

export type InputMode = "off" | "listening" | "thinking" | "speaking";

const IOS =
  /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
/** Interrupting Osky by voice (not on iOS, see above). */
export const canBargeIn = !IOS;

const ASSETS = `${import.meta.env.BASE_URL}vad/`;

// Your turn: normal sensitivity; the turn ends after 0.8 s of silence.
const LISTEN = { positiveSpeechThreshold: 0.5, negativeSpeechThreshold: 0.35, redemptionMs: 800 };
// While Osky talks: only clear, sustained speech counts, so his own voice
// (if the echo canceller lets some through) or a cough don't interrupt him.
const OVER_OSKY = { positiveSpeechThreshold: 0.8, negativeSpeechThreshold: 0.6, redemptionMs: 800 };
const BARGE_IN_PROB = 0.85;
// localStorage "oski.debugVad" = "1" logs the detector's decisions in the console.
const DEBUG = (() => {
  try {
    return localStorage.getItem("oski.debugVad") === "1";
  } catch {
    return false;
  }
})();
const BARGE_IN_MS = 350;

type Callbacks = {
  onBargeIn?: () => void; // the visitor talked over Osky
  onLevel?: (level: number) => void; // 0..1 microphone level while it's their turn
};

export class VoiceInput {
  private mode: InputMode = "off";
  private running = false;
  private segment = { active: false, accepted: false, bargedIn: false };
  private pending: Float32Array | null = null;
  private waiter: ((audio: Float32Array | null) => void) | null = null;
  private onPhase: ((phase: ListenPhase) => void) | null = null;
  private loudMs = 0;

  private constructor(
    private vad: MicVAD,
    private callbacks: Callbacks,
  ) {}

  /** Loads the model (≈2 MB) and the runtime; rejects if the browser can't run it. */
  static async create(audioContext: AudioContext, callbacks: Callbacks = {}): Promise<VoiceInput> {
    const { MicVAD } = await import("@ricky0123/vad-web");
    let input: VoiceInput | null = null;
    const vad = await MicVAD.new({
      model: "v5",
      baseAssetPath: ASSETS,
      onnxWASMBasePath: ASSETS,
      audioContext,
      startOnLoad: false,
      getStream: openMic,
      pauseStream: async (stream) => stream.getTracks().forEach((t) => t.stop()),
      resumeStream: () => openMic(),
      preSpeechPadMs: 300,
      minSpeechMs: 250, // "sí" or "no" are short
      submitUserSpeechOnPause: true,
      ...LISTEN,
      onSpeechStart: () => input?.speechStarted(),
      onSpeechEnd: (audio) => input?.speechEnded(audio),
      onVADMisfire: () => {
        if (input) input.segment.active = false;
      },
      onFrameProcessed: (probs, frame) => input?.frame(probs.isSpeech, frame),
    });
    input = new VoiceInput(vad, callbacks);
    return input;
  }

  /** What Osky is doing: decides which speech counts and keeps the mic open or closed. */
  async setMode(mode: InputMode) {
    if (DEBUG) console.debug("vad mode", this.mode, "->", mode);
    if (mode === this.mode) return;
    this.mode = mode;
    this.loudMs = 0;
    if (mode === "listening") {
      this.vad.setOptions(LISTEN);
      // Speech already going on when the turn starts (they answered right away) counts.
      if (this.segment.active) this.segment.accepted = true;
      await this.run(true);
    } else if (mode === "speaking") {
      this.vad.setOptions(OVER_OSKY);
      await this.run(canBargeIn);
    } else {
      await this.run(mode === "thinking" && canBargeIn);
    }
  }

  /** Waits for the visitor's next utterance and transcribes it. "" = silence or cancelled. */
  listen(opts: { onPhase?: (phase: ListenPhase) => void; onError?: (message: string, blocked?: boolean) => void; maxWaitMs?: number; maxTurnMs?: number } = {}): ListenHandle {
    const maxWaitMs = opts.maxWaitMs ?? 9000;
    const maxTurnMs = opts.maxTurnMs ?? 20000;
    let aborted = false;
    let settle: (audio: Float32Array | null) => void = () => {};
    const timers: number[] = [];

    const audio = new Promise<Float32Array | null>((resolve) => {
      settle = (a) => {
        timers.splice(0).forEach((t) => window.clearTimeout(t));
        this.waiter = null;
        this.onPhase = null;
        resolve(a);
      };
      if (this.pending) {
        const ready = this.pending;
        this.pending = null;
        return settle(ready);
      }
      this.waiter = settle;
      this.onPhase = (phase) => {
        opts.onPhase?.(phase);
        // Someone is talking: no "nobody there" timeout, but a cap on very long turns.
        if (phase === "speaking") timers.push(window.setTimeout(() => void this.endSegment(), maxTurnMs));
      };
      opts.onPhase?.(this.segment.active && this.segment.accepted ? "speaking" : "waiting");
      timers.push(
        window.setTimeout(() => {
          if (!(this.segment.active && this.segment.accepted)) settle(null);
        }, maxWaitMs),
      );
    });

    const result = (async () => {
      const recorded = await audio;
      if (aborted || !recorded) return "";
      opts.onPhase?.("transcribing");
      const { utils } = await import("@ricky0123/vad-web");
      // 16-bit PCM, 16 kHz mono: half the size of the default float WAV (≈32 KB per second).
      const wav = new Blob([utils.encodeWAV(recorded, 1, 16000, 1, 16)], { type: "audio/wav" });
      return aborted ? "" : transcribeOnServer(wav, opts.onError);
    })();

    return {
      result,
      // Tap while listening: end the turn now (what was said so far is used).
      stop: () => (this.segment.active && this.segment.accepted ? void this.endSegment() : settle(null)),
      abort: () => {
        aborted = true;
        settle(null);
      },
    };
  }

  async destroy() {
    this.mode = "off";
    this.waiter?.(null);
    await this.vad.destroy();
  }

  // ---------- detector events ----------

  private async run(on: boolean) {
    if (on === this.running) return;
    this.running = on;
    if (on) await this.vad.start();
    else await this.vad.pause();
  }

  /** Ends the current utterance now (pausing submits it), then keeps listening. */
  private async endSegment() {
    await this.vad.pause();
    if (this.running) await this.vad.start();
  }

  private speechStarted() {
    this.segment = { active: true, accepted: this.mode === "listening", bargedIn: false };
    this.loudMs = 0;
    if (this.segment.accepted) this.onPhase?.("speaking");
  }

  private speechEnded(audio: Float32Array) {
    const accepted = this.segment.accepted;
    this.segment.active = false;
    if (!accepted) return; // noise while Osky was thinking, or his own voice
    if (this.waiter) this.waiter(audio);
    else this.pending = audio; // they talked over Osky: it's the next turn
  }

  private frame(probability: number, frame: Float32Array) {
    const ms = frame.length / 16; // 16 kHz
    if (this.mode === "listening") {
      let sum = 0;
      for (const v of frame) sum += v * v;
      this.callbacks.onLevel?.(Math.min(1, Math.sqrt(sum / frame.length) * 12));
      return;
    }
    if (DEBUG && probability > 0.3) console.debug("vad", this.mode, probability.toFixed(2), this.loudMs, JSON.stringify(this.segment));
    if (this.mode !== "speaking" || !canBargeIn || this.segment.bargedIn || !this.segment.active) return;
    // Clear speech accumulated in this utterance. Natural speech has short dips between
    // syllables, so they don't reset or subtract (that made barge-in almost never fire).
    if (probability > BARGE_IN_PROB) this.loudMs += ms;
    if (this.loudMs >= BARGE_IN_MS) {
      this.segment.accepted = true;
      this.segment.bargedIn = true;
      this.callbacks.onBargeIn?.();
    }
  }
}
