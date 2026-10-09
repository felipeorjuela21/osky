import { useEffect, useRef, useState } from "react";
import { speakText } from "../speech";
import { getMicId, levelMeter, listMics, micOpenError, openMic, setMicId } from "../stt";
import {
  DEFAULT_RATE_PCT,
  VoiceInfo,
  fetchSpeech,
  getTtsRate,
  getTtsVoice,
  listVoices,
  playSpeech,
  setTtsRate,
  setTtsVoice,
} from "../voice";

const SAMPLE = "¡Hola! Soy Osky, el asistente virtual de CeluWeb. ¿En qué te puedo ayudar hoy?";
const LOCALE_ORDER = ["es-CO", "es-MX", "es-US", "es-ES"];

export function VoiceSettings() {
  const [open, setOpen] = useState(false);
  const [voices, setVoices] = useState<VoiceInfo[]>([]);
  const [serverDefault, setServerDefault] = useState("");
  const [voice, setVoice] = useState(getTtsVoice);
  const [rate, setRate] = useState(getTtsRate);
  const [status, setStatus] = useState<string | null>(null);
  const [mics, setMics] = useState<MediaDeviceInfo[]>([]);
  const [micId, setMic] = useState(getMicId);
  const [micLevel, setMicLevel] = useState(0);
  const [micTesting, setMicTesting] = useState(false);
  const [micStatus, setMicStatus] = useState<string | null>(null);
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    void listMics().then(setMics);
  }, [open]);

  /** 5 seconds of live level so the user can see the microphone working. */
  const testMic = async () => {
    setMicTesting(true);
    setMicStatus("Habla ahora…");
    let stream: MediaStream;
    try {
      stream = await openMic();
    } catch (e) {
      setMicStatus(micOpenError(e).message);
      setMicTesting(false);
      return;
    }
    setMics(await listMics()); // device names are only visible after permission
    const meter = levelMeter(stream);
    let peak = 0;
    const t0 = performance.now();
    await new Promise<void>((resolve) => {
      const tick = () => {
        const rms = meter.read();
        peak = Math.max(peak, rms);
        setMicLevel(Math.min(1, rms * 12));
        if (performance.now() - t0 > 5000) return resolve();
        window.setTimeout(tick, 40);
      };
      tick();
    });
    stream.getTracks().forEach((t) => t.stop());
    meter.close();
    setMicLevel(0);
    setMicTesting(false);
    setMicStatus(
      peak > 0.02
        ? "✓ Te escucho bien con este micrófono."
        : peak > 0.004
          ? "Te escucho muy bajo: acércate o sube el volumen de entrada en Windows."
          : "No capto sonido: elige otro micrófono o revisa que no esté silenciado.",
    );
  };

  useEffect(() => {
    if (!open || voices.length) return;
    void listVoices().then((r) => {
      if (!r) return setStatus("La voz neuronal no está disponible; se usará la voz del navegador.");
      setServerDefault(r.default);
      const rank = (v: VoiceInfo) => (LOCALE_ORDER.indexOf(v.locale) + 1 || 99);
      const male = r.voices.filter((v) => v.gender === "Male");
      setVoices([...male].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name)));
      // A voice chosen before (e.g. a female one) that is no longer offered goes back to default.
      if (getTtsVoice() && !male.some((v) => v.name === getTtsVoice())) {
        setTtsVoice("");
        setVoice("");
      }
    });
  }, [open, voices.length]);

  useEffect(() => {
    if (!open) return;
    const close = (e: PointerEvent) => {
      if (!panel.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("pointerdown", close);
    return () => window.removeEventListener("pointerdown", close);
  }, [open]);

  const test = async () => {
    setStatus("Generando voz…");
    const speech = await fetchSpeech(SAMPLE);
    setStatus(speech ? null : "La voz neuronal no respondió; probando la del navegador.");
    if (speech) playSpeech(speech);
    else speakText(SAMPLE);
  };

  const COUNTRY: Record<string, string> = { CO: "Colombia", MX: "México", US: "EE. UU.", ES: "España", AR: "Argentina", CL: "Chile", PE: "Perú", VE: "Venezuela", EC: "Ecuador" };
  const label = (v: VoiceInfo) =>
    `${v.name.replace(/^[a-z]{2}-[A-Z]{2}-/, "").replace(/Neural$/, "")} · ${COUNTRY[v.locale.slice(3)] ?? v.locale}`;

  return (
    <div className="voice-settings" ref={panel}>
      <button className="chip voice-settings__toggle" onClick={() => setOpen(!open)} aria-expanded={open} aria-label="Ajustes de voz y micrófono">
        <span aria-hidden>🎙️</span>
        <span className="chip__label">Voz</span>
      </button>
      {open && (
        <div className="voice-settings__panel">
          <label>
            Voz de Osky
            <select
              value={voice || serverDefault}
              onChange={(e) => {
                setVoice(e.target.value);
                setTtsVoice(e.target.value);
              }}
            >
              {voices.length === 0 && <option value="">Cargando voces…</option>}
              {voices.map((v) => (
                <option key={v.name} value={v.name}>
                  {label(v)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Velocidad: {rate >= 0 ? "+" : ""}
            {rate}%
            <input
              type="range"
              min="-10"
              max="30"
              step="2"
              value={rate}
              onChange={(e) => {
                const value = Number(e.target.value);
                setRate(value);
                setTtsRate(value);
              }}
            />
          </label>
          <label>
            Micrófono
            <select
              value={micId}
              onChange={(e) => {
                setMic(e.target.value);
                setMicId(e.target.value);
                setMicStatus(null);
              }}
            >
              <option value="">Predeterminado de Windows</option>
              {mics
                .filter((m) => m.deviceId && m.deviceId !== "default" && m.deviceId !== "communications")
                .map((m, i) => (
                  <option key={m.deviceId} value={m.deviceId}>
                    {m.label || `Micrófono ${i + 1}`}
                  </option>
                ))}
            </select>
          </label>
          <div className="voice-settings__mic">
            <button className="chip" onClick={() => void testMic()} disabled={micTesting}>
              {micTesting ? "Escuchando…" : "🎤 Probar micrófono"}
            </button>
            <span className="voice-settings__meter" aria-hidden>
              <i style={{ width: `${Math.round(micLevel * 100)}%` }} />
            </span>
          </div>
          {micStatus && <p className="voice-settings__hint">{micStatus}</p>}
          <div className="voice-settings__row">
            <button className="chip chip--on" onClick={() => void test()}>
              ▶ Probar voz
            </button>
            <button
              className="chip"
              onClick={() => {
                setRate(DEFAULT_RATE_PCT);
                setTtsRate(DEFAULT_RATE_PCT);
                setVoice("");
                setTtsVoice("");
              }}
            >
              Restablecer
            </button>
          </div>
          {status && <p className="voice-settings__hint">{status}</p>}
        </div>
      )}
    </div>
  );
}
