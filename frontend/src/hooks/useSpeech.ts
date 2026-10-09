import { useCallback, useEffect, useRef, useState } from "react";
import { ListenHandle, SpeakHandle, canListen, canSpeak, speakText } from "../speech";
import { canRecord, listenTurn } from "../stt";
import { fetchSpeech, playSpeech } from "../voice";

/** Push-to-talk speech for chat mode. */
export function useSpeech(onFinalTranscript: (text: string) => void) {
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [interim, setInterim] = useState("");
  const [mouthOpen, setMouthOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const listenHandle = useRef<ListenHandle | null>(null);
  const speakHandle = useRef<SpeakHandle | null>(null);
  const callback = useRef(onFinalTranscript);
  callback.current = onFinalTranscript;

  useEffect(
    () => () => {
      listenHandle.current?.abort();
      speakHandle.current?.cancel();
    },
    [],
  );

  const stopSpeaking = useCallback(() => {
    speakHandle.current?.cancel();
    setSpeaking(false);
    setMouthOpen(false);
  }, []);

  const speak = useCallback(async (text: string) => {
    speakHandle.current?.cancel();
    const flap = () => {
      setMouthOpen(true);
      window.setTimeout(() => setMouthOpen(false), 120);
    };
    // Neural voice from the backend; the browser voice is only a fallback.
    const speech = await fetchSpeech(text);
    const handle = speech ? playSpeech(speech, flap) : speakText(text, flap);
    speakHandle.current = handle;
    setSpeaking(true);
    await handle.done;
    if (speakHandle.current === handle) {
      setSpeaking(false);
      setMouthOpen(false);
    }
  }, []);

  const startListening = useCallback(() => {
    stopSpeaking(); // barge-in: talking over Osky interrupts it
    setError(null);
    const handle = listenTurn({
      onInterim: setInterim,
      onPhase: (phase) =>
        setInterim(phase === "waiting" ? "Te escucho…" : phase === "speaking" ? "Te oigo…" : "Entendiendo…"),
      onError: (message) => setError(message),
    });
    listenHandle.current = handle;
    setListening(true);
    void handle.result.then((text) => {
      setListening(false);
      setInterim("");
      if (text) callback.current(text);
    });
  }, [stopSpeaking]);

  const stopListening = useCallback(() => listenHandle.current?.stop(), []);

  return { canListen: canListen || canRecord, canSpeak, listening, speaking, interim, mouthOpen, error, speak, stopSpeaking, startListening, stopListening };
}
