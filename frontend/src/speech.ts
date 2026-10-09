/* Browser speech APIs (no keys, no cost). Speech recognition works in
   Chrome and Edge; other browsers can still type and hear Osky. */

export const LANG = "es-CO";

type RecognitionEvent = {
  resultIndex: number;
  results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }>;
};
type Recognition = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((e: RecognitionEvent) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};

const RecognitionCtor: (new () => Recognition) | undefined =
  (window as unknown as { SpeechRecognition?: new () => Recognition }).SpeechRecognition ??
  (window as unknown as { webkitSpeechRecognition?: new () => Recognition }).webkitSpeechRecognition;

export const canListen = Boolean(RecognitionCtor);
export const canSpeak = "speechSynthesis" in window;

if (canSpeak) window.speechSynthesis.getVoices(); // voices load asynchronously in Chrome

const VOICE_KEY = "oski.voice";
const RATE_KEY = "oski.rate";
export const DEFAULT_RATE = 1.12;

function stored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function store(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private mode: preference just isn't remembered */
  }
}

export const getRate = () => Number(stored(RATE_KEY)) || DEFAULT_RATE;
export const setRate = (rate: number) => store(RATE_KEY, String(rate));
export const getVoiceName = () => stored(VOICE_KEY) ?? "";
export const setVoiceName = (name: string) => store(VOICE_KEY, name);

/** Neural voices ("Natural", e.g. Edge's Salome/Gonzalo es-CO) sound far less robotic. */
function voiceScore(v: SpeechSynthesisVoice): number {
  const lang = v.lang.replace("_", "-");
  const langScore = ["es-CO", "es-MX", "es-US", "es-419", "es-ES"].indexOf(lang);
  const quality = /natural/i.test(v.name) ? 0 : /online|neural/i.test(v.name) ? 1 : /google/i.test(v.name) ? 2 : 3;
  return quality * 10 + (langScore === -1 ? 9 : langScore);
}

export function spanishVoices(): SpeechSynthesisVoice[] {
  const voices = canSpeak ? window.speechSynthesis.getVoices() : [];
  return voices.filter((v) => v.lang.toLowerCase().startsWith("es")).sort((a, b) => voiceScore(a) - voiceScore(b));
}

export function onVoicesChanged(callback: () => void): () => void {
  if (!canSpeak) return () => {};
  window.speechSynthesis.addEventListener("voiceschanged", callback);
  return () => window.speechSynthesis.removeEventListener("voiceschanged", callback);
}

// Osky is a man: when the browser's own voices are used, prefer male ones.
const MALE_NAMES = /gonzalo|jorge|alonso|ra[uú]l|pablo|[aá]lvaro|tom[aá]s|diego|andr[eé]s|carlos|juan|jos[eé]|enrique|antonio|male|hombre/i;

function pickVoice(): SpeechSynthesisVoice | undefined {
  const voices = spanishVoices();
  return voices.find((v) => v.name === getVoiceName()) ?? voices.find((v) => MALE_NAMES.test(v.name)) ?? voices[0];
}

export function micErrorMessage(error: string): string | null {
  if (error === "not-allowed" || error === "service-not-allowed") return "Permite el acceso al micrófono para hablar con Osky.";
  if (error === "no-speech" || error === "aborted") return null;
  return `Error de micrófono: ${error}`;
}

export type ListenHandle = { result: Promise<string>; stop: () => void; abort: () => void };

/** Listens for one utterance. Resolves with the transcript ("" if nothing was said).
    Ends the turn after endSilenceMs without new words, quicker than the browser's own cut-off. */
export function listenOnce(
  onInterim?: (text: string) => void,
  onError?: (error: string) => void,
  endSilenceMs = 800,
): ListenHandle {
  if (!RecognitionCtor) return { result: Promise.resolve(""), stop: () => {}, abort: () => {} };
  const rec = new RecognitionCtor();
  rec.lang = LANG;
  rec.interimResults = true;
  rec.continuous = false;
  let finalText = "";
  let partial = "";
  let aborted = false;
  let silence = 0;
  rec.onresult = (event) => {
    window.clearTimeout(silence);
    silence = window.setTimeout(() => rec.stop(), endSilenceMs);
    partial = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i];
      if (result.isFinal) finalText += result[0].transcript;
      else partial += result[0].transcript;
    }
    onInterim?.(finalText + partial);
  };
  rec.onerror = (event) => onError?.(event.error);
  const result = new Promise<string>((resolve) => {
    rec.onend = () => {
      window.clearTimeout(silence);
      resolve(aborted ? "" : (finalText || partial).trim());
    };
  });
  try {
    rec.start();
  } catch {
    return { result: Promise.resolve(""), stop: () => {}, abort: () => {} };
  }
  return {
    result,
    stop: () => rec.stop(),
    abort: () => {
      aborted = true;
      rec.abort();
    },
  };
}

export type SpeakHandle = { done: Promise<void>; cancel: () => void };

/** Splits into sentences: Chrome's network voices stop long utterances after ~15 s. */
function sentences(text: string): { text: string; offset: number }[] {
  const parts: { text: string; offset: number }[] = [];
  const re = /[^.!?¿¡]+[.!?]*|[¿¡][^?!]*[?!]?/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(text))) {
    if (match[0].trim()) parts.push({ text: match[0], offset: match.index });
  }
  return parts.length ? parts : [{ text, offset: 0 }];
}

/** Rough speaking time of a word, used when the voice gives no word events. */
export const wordMs = (word: string, rate = getRate()) =>
  (85 + word.length * 55 + (/[.,:;!?]$/.test(word) ? 240 : 0)) / rate;

/** Speaks text; onWord receives the char index of each word as it is spoken. */
export function speakText(text: string, onWord?: (charIndex: number) => void): SpeakHandle {
  let cancelled = false;
  const timers: number[] = [];
  const clear = () => timers.splice(0).forEach((t) => window.clearTimeout(t));

  const speakPart = (part: { text: string; offset: number }) =>
    new Promise<void>((resolve) => {
      const words = [...part.text.matchAll(/\S+/g)];
      const estimate = words.reduce((ms, w) => ms + wordMs(w[0]), 0);
      if (!canSpeak) {
        // No TTS: still animate the captions at speaking pace.
        let t = 0;
        words.forEach((w) => {
          timers.push(window.setTimeout(() => onWord?.(part.offset + (w.index ?? 0)), t));
          t += wordMs(w[0]);
        });
        timers.push(window.setTimeout(resolve, t));
        return;
      }
      const utterance = new SpeechSynthesisUtterance(part.text);
      utterance.lang = LANG;
      const voice = pickVoice();
      if (voice) utterance.voice = voice;
      utterance.rate = getRate();
      let realBoundaries = false;
      let finished = false;
      const finish = () => {
        if (finished) return;
        finished = true;
        clear();
        resolve();
      };
      utterance.onstart = () => {
        let t = 0;
        words.forEach((w) => {
          timers.push(
            window.setTimeout(() => {
              if (!realBoundaries && !cancelled) onWord?.(part.offset + (w.index ?? 0));
            }, t),
          );
          t += wordMs(w[0]);
        });
        // Watchdog: some Chrome voices never fire onend.
        timers.push(window.setTimeout(finish, estimate * 1.6 + 3000));
      };
      utterance.onboundary = (e) => {
        if (e.name && e.name !== "word") return;
        realBoundaries = true;
        onWord?.(part.offset + e.charIndex);
      };
      utterance.onend = finish;
      utterance.onerror = finish;
      window.speechSynthesis.speak(utterance);
    });

  if (canSpeak) window.speechSynthesis.cancel();
  // One continuous utterance sounds more natural; split only where Chrome needs it.
  const splitNeeded = /google/i.test(pickVoice()?.name ?? "") && text.length > 160;
  const parts = splitNeeded ? sentences(text) : [{ text, offset: 0 }];
  const done = (async () => {
    for (const part of parts) {
      if (cancelled) return;
      await speakPart(part);
    }
  })();

  return {
    done,
    cancel: () => {
      cancelled = true;
      clear();
      if (canSpeak) window.speechSynthesis.cancel();
    },
  };
}
