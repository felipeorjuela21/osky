/* Plays Osky's neural voice through Web Audio and reports its loudness every
   frame, so the astronaut moves with the real voice (not an estimate). */

import { speakText } from "./speech";
import { Speech, base64ToArrayBuffer, playSpeech } from "./voice";

export type Playback = { done: Promise<void>; cancel: () => void };

let ctx: AudioContext | null = null;

function audioContext(): AudioContext {
  if (!ctx) ctx = new AudioContext();
  return ctx;
}

/** Call inside a click handler: browsers only allow audio after a user action. */
export function unlockAudio() {
  const c = audioContext();
  void c.resume();
  try {
    // Some browsers only unlock when a sound actually starts inside the gesture.
    const src = c.createBufferSource();
    src.buffer = c.createBuffer(1, 1, 22050);
    src.connect(c.destination);
    src.start(0);
  } catch {
    /* ignore */
  }
}

/** Loudness envelope from word timings, for players we cannot analyse. */
function simulatedLevels(onLevel: (level: number) => void) {
  let frame = 0;
  const tick = () => {
    onLevel(0.45 + Math.random() * 0.4);
    frame = window.setTimeout(tick, 90);
  };
  tick();
  return () => {
    window.clearTimeout(frame);
    onLevel(0);
  };
}

/**
 * Speaks `text` with the neural voice when available (browser voice otherwise).
 * onLevel: 0..1 loudness ~60 times per second. onWord: index of the word now spoken.
 */
export async function speakWithLevels(
  text: string,
  speech: Speech | null,
  { onLevel, onWord }: { onLevel?: (level: number) => void; onWord?: (index: number) => void } = {},
): Promise<Playback> {
  const c = audioContext();
  if (c.state !== "running") {
    await Promise.race([c.resume(), new Promise((r) => window.setTimeout(r, 1200))]);
  }

  // Fallbacks: <audio> element or the browser's voice, with a simulated envelope.
  if (!speech || c.state !== "running") {
    const stop = onLevel ? simulatedLevels(onLevel) : () => {};
    let handle: Playback;
    if (speech) {
      const element = playSpeech(speech, onWord);
      handle = (await element.started) ? element : speakText(text);
    } else {
      const words = [...text.matchAll(/\S+/g)];
      handle = speakText(text, (charIndex) => {
        const i = words.findIndex((w) => (w.index ?? 0) >= charIndex);
        onWord?.(i === -1 ? words.length - 1 : i);
      });
    }
    void handle.done.then(stop);
    return { done: handle.done, cancel: () => (handle.cancel(), stop()) };
  }

  const buffer = await c.decodeAudioData(base64ToArrayBuffer(speech.audio));
  const source = c.createBufferSource();
  source.buffer = buffer;
  const analyser = c.createAnalyser();
  analyser.fftSize = 1024;
  source.connect(analyser);
  analyser.connect(c.destination);

  const samples = new Float32Array(analyser.fftSize);
  const timers: number[] = [];
  let frame = 0;
  let resolveDone: () => void = () => {};
  const done = new Promise<void>((resolve) => (resolveDone = resolve));
  const finish = () => {
    cancelAnimationFrame(frame);
    timers.splice(0).forEach((t) => window.clearTimeout(t));
    onLevel?.(0);
    resolveDone();
  };
  const tick = () => {
    analyser.getFloatTimeDomainData(samples);
    let sum = 0;
    for (const v of samples) sum += v * v;
    onLevel?.(Math.min(1, Math.sqrt(sum / samples.length) * 5.5));
    frame = requestAnimationFrame(tick);
  };

  source.onended = finish;
  source.start();
  tick();
  speech.words.forEach((w, i) => timers.push(window.setTimeout(() => onWord?.(i), w.start * 1000)));

  return {
    done,
    cancel: () => {
      try {
        source.stop();
      } catch {
        /* already stopped */
      }
      finish();
    },
  };
}
