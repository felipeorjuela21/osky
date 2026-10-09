import { setAudioSession } from "./voice";
import { apiUrl } from "./api";
/* Listening to the user: records one turn from the microphone, detects when the
   person starts and stops talking, and transcribes it with Whisper on our server
   (/api/stt). Falls back to the browser's recognition if the server can't. */

import { ListenHandle, canListen, listenOnce, micErrorMessage } from "./speech";

export type ListenPhase = "waiting" | "speaking" | "transcribing";
export type ListenOptions = {
  onLevel?: (level: number) => void; // 0..1, for a live meter
  onPhase?: (phase: ListenPhase) => void;
  onError?: (message: string, blocked?: boolean) => void;
  onInterim?: (text: string) => void; // only with the browser fallback
  maxWaitMs?: number; // give up if nobody talks
  endSilenceMs?: number; // silence that ends the turn
  maxTurnMs?: number;
};

const MIC_KEY = "oski.micId";

export function getMicId(): string {
  try {
    return localStorage.getItem(MIC_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setMicId(id: string) {
  try {
    localStorage.setItem(MIC_KEY, id);
  } catch {
    /* private mode */
  }
}

export async function listMics(): Promise<MediaDeviceInfo[]> {
  if (!navigator.mediaDevices) return [];
  const devices = await navigator.mediaDevices.enumerateDevices();
  return devices.filter((d) => d.kind === "audioinput");
}

// mediaDevices is undefined outside secure contexts (http on a non-localhost host).
export const canRecord = Boolean(navigator.mediaDevices) && "MediaRecorder" in window;

/** Opens the chosen microphone (or the default one). */
export async function openMic(): Promise<MediaStream> {
  setAudioSession("play-and-record"); // iPhone: recording needs this session (speech switches back to "playback")
  const id = getMicId();
  const audio: MediaTrackConstraints = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
  try {
    return await navigator.mediaDevices.getUserMedia({ audio: id ? { ...audio, deviceId: { exact: id } } : audio });
  } catch (e) {
    // The saved device may have been unplugged: retry with the default one.
    if (id && (e as DOMException).name === "OverconstrainedError") {
      setMicId("");
      return navigator.mediaDevices.getUserMedia({ audio });
    }
    throw e;
  }
}

export function micOpenError(e: unknown): { message: string; blocked: boolean } {
  const name = (e as DOMException)?.name;
  if (name === "NotAllowedError" || name === "SecurityError")
    return { message: "Chrome bloqueó el micrófono. Haz clic en el candado de la barra de direcciones y permite el micrófono.", blocked: true };
  if (name === "NotFoundError") return { message: "No encontré ningún micrófono conectado.", blocked: true };
  if (name === "NotReadableError")
    return { message: "El micrófono está siendo usado por otra aplicación (Teams, Zoom…). Ciérrala e inténtalo de nuevo.", blocked: false };
  return { message: `No pude abrir el micrófono (${name ?? "error"}).`, blocked: false };
}

/** Measures loudness (RMS) of a stream; returns a reader and a cleanup function. */
export function levelMeter(stream: MediaStream) {
  const ctx = new AudioContext();
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  ctx.createMediaStreamSource(stream).connect(analyser);
  const buf = new Float32Array(analyser.fftSize);
  return {
    read() {
      analyser.getFloatTimeDomainData(buf);
      let sum = 0;
      for (const v of buf) sum += v * v;
      return Math.sqrt(sum / buf.length);
    },
    close() {
      void ctx.close();
    },
  };
}

let serverSttAvailable = true;

function pickMimeType(): string {
  const options = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
  return options.find((t) => MediaRecorder.isTypeSupported(t)) ?? "";
}

export function listenTurn(opts: ListenOptions = {}): ListenHandle {
  if (!canRecord || !serverSttAvailable) {
    // Browser recognition (Chrome/Edge cloud service).
    if (!canListen) return { result: Promise.resolve(""), stop: () => {}, abort: () => {} };
    opts.onPhase?.("waiting");
    return listenOnce(opts.onInterim, (e) => {
      const message = micErrorMessage(e);
      if (message) opts.onError?.(message, e === "not-allowed" || e === "service-not-allowed");
    });
  }

  const maxWaitMs = opts.maxWaitMs ?? 9000;
  const endSilenceMs = opts.endSilenceMs ?? 900;
  const maxTurnMs = opts.maxTurnMs ?? 20000;
  let aborted = false;
  let stopRequested = false;

  const result = (async (): Promise<string> => {
    let stream: MediaStream;
    try {
      stream = await openMic();
    } catch (e) {
      const { message, blocked } = micOpenError(e);
      opts.onError?.(message, blocked);
      return "";
    }
    const meter = levelMeter(stream);
    const mimeType = pickMimeType();
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks: Blob[] = [];
    recorder.ondataavailable = (e) => {
      if (e.data.size) chunks.push(e.data);
    };
    recorder.start(250);
    opts.onPhase?.("waiting");

    // Voice activity detection on the loudness envelope.
    let heard = false;
    let peak = 0;
    await new Promise<void>((resolve) => {
      const t0 = performance.now();
      let last = t0;
      let floor = 0;
      let samples = 0;
      let speechMs = 0;
      let silenceMs = 0;
      const tick = () => {
        if (aborted || stopRequested) return resolve();
        const now = performance.now();
        const dt = now - last;
        last = now;
        const rms = meter.read();
        peak = Math.max(peak, rms);
        if (now - t0 < 350) {
          floor = (floor * samples + rms) / (samples + 1); // ambient noise
          samples++;
        }
        const threshold = Math.max(0.012, floor * 2.8);
        opts.onLevel?.(Math.min(1, rms / (threshold * 4)));
        if (rms > threshold) {
          speechMs += dt;
          silenceMs = 0;
          if (!heard && speechMs > 150) {
            heard = true;
            opts.onPhase?.("speaking");
          }
        } else if (heard) {
          silenceMs += dt;
        } else {
          speechMs = Math.max(0, speechMs - dt);
        }
        if (heard && silenceMs > endSilenceMs) return resolve();
        if (!heard && now - t0 > maxWaitMs) return resolve();
        if (now - t0 > maxTurnMs) return resolve();
        window.setTimeout(tick, 30);
      };
      tick();
    });

    const stopped = new Promise((r) => (recorder.onstop = r));
    recorder.stop();
    await stopped;
    stream.getTracks().forEach((t) => t.stop());
    setAudioSession("playback"); // back to the loudspeaker for Osky's answer
    meter.close();
    opts.onLevel?.(0);

    if (aborted) return "";
    if (!heard && !stopRequested) {
      if (peak < 0.004) {
        opts.onError?.("No escuché nada. Si hablaste, tu micrófono no está captando sonido: revisa que no esté silenciado o elige otro en 🎙️ Voz → Probar micrófono.");
      }
      return "";
    }

    opts.onPhase?.("transcribing");
    const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
    try {
      const response = await fetch(apiUrl("/api/stt"), { method: "POST", headers: { "Content-Type": blob.type }, body: blob });
      if (response.status === 503) {
        serverSttAvailable = false; // use the browser's recognition from now on
        opts.onError?.("El reconocimiento de voz del servidor no está disponible; uso el del navegador.");
        return "";
      }
      if (!response.ok) throw new Error(String(response.status));
      return ((await response.json()) as { text: string }).text.trim();
    } catch {
      opts.onError?.("No pude transcribir tu voz. ¿Está corriendo el servidor de Osky?");
      return "";
    }
  })();

  return {
    result,
    stop: () => {
      stopRequested = true;
    },
    abort: () => {
      aborted = true;
    },
  };
}
