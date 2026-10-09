import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Action, AgentInfo, Source, ask, sendName, startConversation, topicOf } from "../api";
import { ActionButtons, SourceLabel } from "./Actions";
import { useSpeech } from "../hooks/useSpeech";
import { AgentState, OskiAvatar } from "./OskiAvatar";

type Message = {
  id: number;
  role: "user" | "oski";
  text: string;
  sources?: Source[];
  actions?: Action[];
  notFound?: boolean;
  privacy?: boolean; // shows the data-policy note under the greeting
};

export const PRIVACY_URL = "https://www.celuweb.com/?page_id=18917";
/** A reply that is clearly a question (not a name) also gets answered. */
export const looksLikeQuestion = (text: string) => /[?¿]/.test(text) || text.trim().split(/\s+/).length > 3;

const SUGGESTIONS = [
  "¿Qué servicios ofrece CeluWeb?",
  "¿Qué es TMS?",
  "¿Tienen algo para WhatsApp?",
  "¿Cuál es la misión de CeluWeb?",
  "¿Cómo los contacto?",
  "Quiero hablar con un asesor",
];

const BACKEND_ERROR = "No pude conectarme con el servidor de Osky. Inténtalo de nuevo en un momento.";

let nextId = 1;

export function ChatView({ agent }: { agent: AgentInfo | null }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [voiceOn, setVoiceOn] = useState(true);
  const [backendError, setBackendError] = useState<string | null>(null);
  const listEnd = useRef<HTMLDivElement>(null);
  const topic = useRef<string | null>(null);
  // Osky asks the visitor's name first; every turn is logged in this conversation.
  const conversationId = useRef<string | null>(null);
  const askingName = useRef(false);
  const nameAttempt = useRef(1);
  const [waitingName, setWaitingName] = useState(false);
  const voiceOnRef = useRef(voiceOn);
  voiceOnRef.current = voiceOn;

  const push = (message: Omit<Message, "id">) => setMessages((m) => [...m, { ...message, id: nextId++ }]);

  const say = (text: string) => {
    if (voiceOnRef.current) void speech.speak(text);
  };

  const handleQuestion = useCallback(async (question: string) => {
    const text = question.trim();
    if (!text) return;
    push({ role: "user", text });
    setInput("");
    setThinking(true);
    try {
      if (askingName.current && conversationId.current) {
        const result = await sendName(conversationId.current, text, nameAttempt.current);
        nameAttempt.current += 1;
        push({ role: "oski", text: result.reply });
        if (result.status !== "retry") {
          askingName.current = false;
          setWaitingName(false);
        }
        // Not a name but a real question after insisting once: answer it too.
        if (result.status !== "skip" || !looksLikeQuestion(text)) {
          say(result.reply);
          return;
        }
      }
      const response = await ask(text, "chat", topic.current, conversationId.current);
      topic.current = topicOf(response) ?? topic.current;
      push({
        role: "oski",
        text: response.answer,
        sources: response.sources,
        actions: response.actions,
        notFound: response.status !== "ok",
      });
      setBackendError(null);
      say(response.answer);
    } catch {
      setBackendError(BACKEND_ERROR);
    } finally {
      setThinking(false);
    }
  }, []);

  const speech = useSpeech(handleQuestion);

  const greeted = useRef(false); // StrictMode runs effects twice in development
  useEffect(() => {
    if (!agent || greeted.current) return;
    greeted.current = true;
    startConversation("chat")
      .then((conversation) => {
        conversationId.current = conversation.id;
        askingName.current = true;
        setWaitingName(true);
        push({ role: "oski", text: conversation.greeting, privacy: true });
      })
      .catch(() => push({ role: "oski", text: agent.greeting })); // keeps working without the log
  }, [agent]);

  useEffect(() => {
    listEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, thinking]);

  const state: AgentState = speech.listening ? "listening" : thinking ? "thinking" : speech.speaking ? "speaking" : "idle";

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void handleQuestion(input);
  };

  return (
    <main className="layout">
      <section className="stage">
        <OskiAvatar state={state} mouthOpen={speech.mouthOpen} />
        {speech.canListen ? (
          <button
            className={`mic ${speech.listening ? "mic--on" : ""}`}
            onClick={() => (speech.listening ? speech.stopListening() : speech.startListening())}
            aria-label={speech.listening ? "Dejar de escuchar" : "Hablar con Osky"}
          >
            <svg viewBox="0 0 24 24" width="30" height="30" aria-hidden>
              <path
                fill="currentColor"
                d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2Z"
              />
            </svg>
          </button>
        ) : (
          <p className="hint">Tu navegador no permite dictado por voz. Usa Chrome o Edge, o escribe tu pregunta.</p>
        )}
        <p className="interim">{speech.interim || (speech.canListen ? "Toca el micrófono y pregunta" : "")}</p>
        {speech.error && <p className="error">{speech.error}</p>}
        <button
          className={`chip ${voiceOn ? "chip--on" : ""}`}
          onClick={() => {
            if (voiceOn) speech.stopSpeaking();
            setVoiceOn(!voiceOn);
          }}
          aria-pressed={voiceOn}
        >
          {voiceOn ? "🔊 Voz activada" : "🔇 Voz desactivada"}
        </button>
      </section>

      <section className="chat">
        <div className="messages">
          {messages.map((m) => (
            <div key={m.id} className={`bubble bubble--${m.role} ${m.notFound ? "bubble--muted" : ""}`}>
              <p>{m.text}</p>
              <ActionButtons actions={m.actions} />
              <SourceLabel source={m.sources?.[0]} className="source" />
              {m.privacy && (
                <p className="privacy-note">
                  Guardamos tu nombre y tus preguntas para atenderte mejor.{" "}
                  <a href={PRIVACY_URL} target="_blank" rel="noreferrer">
                    Política de datos
                  </a>
                </p>
              )}
            </div>
          ))}
          {thinking && <div className="bubble bubble--oski bubble--typing">…</div>}
          <div ref={listEnd} />
        </div>

        {backendError && <p className="error">{backendError}</p>}

        {/* Suggestions appear once Osky knows the visitor's name. */}
        {!waitingName && (
          <div className="suggestions">
            {SUGGESTIONS.map((s) => (
              <button key={s} className="chip" onClick={() => void handleQuestion(s)} disabled={thinking}>
                {s}
              </button>
            ))}
          </div>
        )}

        <form className="composer" onSubmit={onSubmit}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={waitingName ? "Escribe tu nombre…" : "Escribe tu pregunta sobre CeluWeb…"}
            maxLength={500}
            aria-label={waitingName ? "Tu nombre" : "Pregunta"}
          />
          <button type="submit" disabled={!input.trim() || thinking}>
            Enviar
          </button>
        </form>
      </section>
    </main>
  );
}
