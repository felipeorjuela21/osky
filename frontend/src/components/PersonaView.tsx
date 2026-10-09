import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Action, AgentInfo, Source, ask, logTurn, sendName, startConversation, topicOf } from "../api";
import { Playback, speakWithLevels, unlockAudio } from "../audio";
import { ListenHandle, canListen } from "../speech";
import { ListenPhase, canRecord, listenTurn } from "../stt";
import { Speech, fetchSpeech, wordOffsets } from "../voice";
import { ActionButtons, SourceLabel } from "./Actions";
import { looksLikeQuestion } from "./ChatView";
import { OskiRig, RigGesture, RigMood } from "./OskiRig";
import "./persona.css";

type State = "idle" | "listening" | "thinking" | "speaking";
type Entrance = "" | "arrive" | "leave";

const LISTEN_STATUS: Record<ListenPhase, string> = {
  waiting: "Te escucho… habla cuando quieras",
  speaking: "Te oigo…",
  transcribing: "Entendiendo…",
};

const STATUS: Record<State, string> = {
  idle: "",
  listening: "Te escucho…",
  thinking: "Pensando…",
  speaking: "Hablando · toca a Osky o pulsa espacio para interrumpir",
};

const MORE_PROMPTS = ["¿Te cuento más?", "¿Quieres más detalles?", "¿Te sigo contando?"];
const YES = /^(si|sip|claro|dale|ok|okey|bueno|por favor|cuentame( mas)?|mas|quiero saber mas|de una|obvio|sigue|continua)\b/;
const NO = /^(no|nop|asi esta bien|no gracias|listo gracias|esta bien)\b/;
const MAX_SILENT_TURNS = 2;

const sleep = (ms: number) => new Promise((r) => window.setTimeout(r, ms));
const pick = <T,>(items: T[]) => items[Math.floor(Math.random() * items.length)];
const normalize = (text: string) =>
  text.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-zñ0-9 ]/g, "").trim();

/* Starfield generated once: three layers drifting at different speeds. */
function starLayer(count: number, size: number) {
  const shadows = Array.from({ length: count }, () => {
    const x = Math.round(Math.random() * 2400);
    const y = Math.round(Math.random() * 2400);
    const a = (0.35 + Math.random() * 0.65).toFixed(2);
    return `${x}px ${y}px rgba(255,255,255,${a})`;
  });
  return { width: size, height: size, boxShadow: shadows.join(",") };
}

export function PersonaView({ agent }: { agent: AgentInfo | null }) {
  const [active, setActive] = useState(false);
  const [state, setState] = useState<State>("idle");
  const [mood, setMood] = useState<RigMood>("neutral");
  const [gesture, setGesture] = useState<RigGesture>("");
  const [entrance, setEntrance] = useState<Entrance>("arrive");
  const [oskiText, setOskiText] = useState("");
  const [spokenUntil, setSpokenUntil] = useState(-1);
  const [userText, setUserText] = useState("");
  const [source, setSource] = useState<Source | null>(null);
  const [actions, setActions] = useState<Action[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [typed, setTyped] = useState("");
  const [phase, setPhase] = useState<ListenPhase>("waiting");
  const [visitorName, setVisitorName] = useState<string | null>(null);
  const conversationId = useRef<string | null>(null);

  const root = useRef<HTMLDivElement>(null);
  const session = useRef(0);
  const playback = useRef<Playback | null>(null);
  const listenHandle = useRef<ListenHandle | null>(null);
  const typedTurn = useRef<((text: string) => void) | null>(null);
  const micBlocked = useRef(false);
  const pendingMore = useRef("");
  const topic = useRef<string | null>(null);
  const voiceLevel = useRef(0);
  const talk = useRef(0);
  const look = useRef({ x: 0, y: 0, tx: 0, ty: 0, lastPointer: 0 });
  const stateRef = useRef<State>("idle");
  stateRef.current = state;

  const stars = useMemo(() => [starLayer(260, 1), starLayer(90, 2), starLayer(35, 3)], []);

  const name = agent?.name ?? "Osky";
  const company = agent?.company ?? "CeluWeb";
  const greeting = `¡Hola! Soy ${name}, el asistente virtual de ${company}. Antes de empezar, ¿cómo te llamas?`;

  // Warm up the greeting's neural voice so the first words come out instantly.
  const greetingSpeech = useRef<Promise<Speech | null> | null>(null);
  useEffect(() => {
    greetingSpeech.current = fetchSpeech(greeting);
  }, [greeting]);

  // Every frame: the real voice loudness becomes head nods, hand beats and visor
  // light (--talk), and the gaze eases towards its target (--look-x/--look-y).
  useEffect(() => {
    let frame = 0;
    const tick = () => {
      const el = root.current;
      const l = look.current;
      talk.current += (voiceLevel.current - talk.current) * 0.35;
      l.x += (l.tx - l.x) * 0.07;
      l.y += (l.ty - l.y) * 0.07;
      el?.style.setProperty("--talk", talk.current.toFixed(3));
      el?.style.setProperty("--look-x", l.x.toFixed(3));
      el?.style.setProperty("--look-y", l.y.toFixed(3));
      frame = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(frame);
  }, []);

  // Osky looks at your pointer; when idle it glances around, and while listening
  // it looks straight at you.
  useEffect(() => {
    const clamp = (v: number) => Math.max(-1, Math.min(1, v));
    const onMove = (e: PointerEvent) => {
      const rect = root.current?.getBoundingClientRect();
      if (!rect) return;
      const l = look.current;
      l.tx = clamp((e.clientX - (rect.left + rect.width / 2)) / (rect.width / 2));
      l.ty = clamp((e.clientY - (rect.top + rect.height * 0.4)) / (rect.height / 2));
      l.lastPointer = Date.now();
    };
    const glance = window.setInterval(() => {
      const l = look.current;
      if (stateRef.current === "listening") {
        l.tx = 0;
        l.ty = 0.1;
      } else if (stateRef.current === "thinking") {
        l.tx = 0.6;
        l.ty = -0.5; // looks up and aside while thinking
      } else if (Date.now() - l.lastPointer > 4000) {
        l.tx = Math.random() < 0.6 ? (Math.random() - 0.5) * 1.1 : 0;
        l.ty = Math.random() < 0.6 ? (Math.random() - 0.5) * 0.6 : 0;
      }
    }, 1800);
    window.addEventListener("pointermove", onMove);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.clearInterval(glance);
    };
  }, []);

  const playGesture = useCallback((g: RigGesture, ms = 1500) => {
    setGesture(g);
    window.setTimeout(() => setGesture((current) => (current === g ? "" : current)), ms);
  }, []);

  useEffect(() => {
    const t = window.setTimeout(() => setEntrance(""), 1700);
    return () => window.clearTimeout(t);
  }, []);

  const say = useCallback(
    async (text: string, id: number, feeling: RigMood = "neutral", speech?: Promise<Speech | null> | null) => {
      if (session.current !== id) return;
      const audio = await (speech ?? fetchSpeech(text));
      if (session.current !== id) return;
      setMood(feeling);
      setOskiText(text);
      setSpokenUntil(-1);
      setState("speaking");
      const offsets = audio ? wordOffsets(text, audio.words) : [];
      const words = [...text.matchAll(/\S+/g)];
      const handle = await speakWithLevels(text, audio, {
        onLevel: (level) => (voiceLevel.current = level),
        onWord: (i) => setSpokenUntil(audio ? offsets[i] ?? 0 : words[i]?.index ?? 0),
      });
      playback.current = handle;
      await handle.done;
      voiceLevel.current = 0;
      if (session.current === id) {
        setSpokenUntil(Number.MAX_SAFE_INTEGER);
        setMood("neutral");
      }
    },
    [],
  );

  /** Resolves with what the user said (voice) or typed. "" means silence. */
  const userTurn = useCallback((id: number) => {
    return new Promise<string>((resolve) => {
      let settled = false;
      const finish = (text: string) => {
        if (settled) return;
        settled = true;
        typedTurn.current = null;
        resolve(text);
      };
      typedTurn.current = (text) => {
        listenHandle.current?.abort();
        finish(text);
      };
      if ((!canRecord && !canListen) || micBlocked.current || session.current !== id) return; // wait for typed text
      const handle = listenTurn({
        onLevel: (level) => root.current?.style.setProperty("--mic", level.toFixed(2)),
        onPhase: setPhase,
        onInterim: setUserText,
        onError: (message, blocked) => {
          if (blocked) micBlocked.current = true;
          setError(message);
        },
      });
      listenHandle.current = handle;
      void handle.result.then((text) => {
        if (text) setError(null);
        finish(text);
      });
    });
  }, []);

  const end = useCallback(() => {
    session.current++;
    playback.current?.cancel();
    listenHandle.current?.abort();
    typedTurn.current = null;
    pendingMore.current = "";
    voiceLevel.current = 0;
    setActive(false);
    setState("idle");
  }, []);

  useEffect(() => end, [end]);

  /** Listens for one turn; handles silence and a blocked microphone. null = conversation ended. */
  const nextTurn = useCallback(
    async (id: number, silent: { count: number }, nudge: string): Promise<string | null> => {
      while (session.current === id) {
        setState("listening");
        setUserText("");
        const heard = (await userTurn(id)).trim();
        if (session.current !== id) return null;
        if (heard) {
          silent.count = 0;
          setUserText(heard);
          return heard;
        }
        if (micBlocked.current) {
          await say("No puedo usar tu micrófono. Revisa el mensaje en pantalla, o escríbeme abajo y te respondo.", id);
          continue;
        }
        silent.count++;
        if (silent.count >= MAX_SILENT_TURNS) {
          await say("Parece que no estás por ahí. Cuando quieras seguimos, solo toca el botón.", id, "unsure");
          if (session.current === id) end();
          return null;
        }
        await say(nudge, id);
      }
      return null;
    },
    [end, say, userTurn],
  );

  const start = useCallback(async () => {
    unlockAudio(); // must run inside the click: browsers block audio otherwise
    const id = ++session.current;
    const alive = () => session.current === id;
    setActive(true);
    setError(null);
    setUserText("");
    setVisitorName(null);
    setSource(null);
    setActions([]);
    topic.current = null;

    // The conversation is created while Osky says hello (it logs name and questions).
    const conversation = startConversation("persona").catch(() => null);
    playGesture("wave", 1800);
    await say(greeting, id, "happy", greetingSpeech.current);
    conversationId.current = (await conversation)?.id ?? null;
    const silent = { count: 0 };

    // 1. The visitor's name first, to talk to them personally.
    let firstQuestion: string | null = null;
    if (conversationId.current) {
      for (let attempt = 1; alive(); attempt++) {
        const heard = await nextTurn(id, silent, "¿Me dices tu nombre? Así te atiendo mejor.");
        if (heard === null) return;
        const result = await sendName(conversationId.current, heard, attempt).catch(() => null);
        if (!alive()) return;
        if (!result) break; // the log is unavailable: keep talking anyway
        if (result.name) setVisitorName(result.name);
        if (result.status === "retry") {
          await say(result.reply, id);
          continue;
        }
        if (result.status === "skip" && looksLikeQuestion(heard)) {
          firstQuestion = heard; // it was a question: answer it right away
          break;
        }
        if (result.status === "ok") playGesture("nod", 900);
        await say(result.reply, id, "happy");
        break;
      }
    }

    // 2. The conversation.
    while (alive()) {
      const question = firstQuestion ?? (await nextTurn(id, silent, "¿Sigues ahí? Puedes preguntarme por las soluciones de CeluWeb o pedirme un asesor."));
      firstQuestion = null;
      if (question === null || !alive()) return;
      playGesture("nod", 900); // "entendido"

      // "¿Te cuento más?" -> "sí": continue with the rest of the previous answer.
      const more = pendingMore.current;
      pendingMore.current = "";
      if (more && YES.test(normalize(question))) {
        logTurn(conversationId.current, question, more, "answer");
        await say(more, id);
        continue;
      }
      if (more && NO.test(normalize(question))) {
        const reply = pick(["¡Listo! ¿Qué más quieres saber?", "Perfecto. ¿Te ayudo con algo más?"]);
        logTurn(conversationId.current, question, reply, "more_no");
        await say(reply, id, "happy");
        continue;
      }

      setState("thinking");
      let response;
      try {
        response = await ask(question, "voice", topic.current, conversationId.current);
      } catch {
        if (!alive()) return;
        await say("Uy, no pude conectarme con el servidor. Inténtalo de nuevo en un momento.", id, "unsure");
        if (alive()) end();
        return;
      }
      if (!alive()) return;

      setSource(response.sources[0] ?? null);
      setActions(response.actions ?? []);
      topic.current = topicOf(response) ?? topic.current;
      pendingMore.current = response.more ?? "";
      // The server already words it warmly and with the visitor's name ("Claro, Ana. ...").
      const text = pendingMore.current ? `${response.answer} ${pick(MORE_PROMPTS)}` : response.answer;

      if (response.intent === "not_found") playGesture("shrug", 1300);
      else if (["greeting", "goodbye", "thanks", "sales"].includes(response.intent)) playGesture("wave", 1800);
      const feeling: RigMood =
        response.intent === "not_found" ? "unsure" : response.intent === "answer" ? "neutral" : "happy";
      await say(text, id, feeling);

      if (response.intent === "goodbye" && alive()) {
        setEntrance("leave"); // floats away...
        await sleep(1700);
        end();
        setEntrance("arrive"); // ...and comes back for the next person
        window.setTimeout(() => setEntrance(""), 1700);
        return;
      }
    }
  }, [end, greeting, nextTurn, playGesture, say]);

  const interrupt = useCallback(() => {
    if (stateRef.current === "speaking") playback.current?.cancel();
    else if (stateRef.current === "listening") listenHandle.current?.stop();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== "Space" || !active || (e.target as HTMLElement).tagName === "INPUT") return;
      e.preventDefault();
      interrupt();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, interrupt]);

  const onType = (e: FormEvent) => {
    e.preventDefault();
    const text = typed.trim();
    if (!text) return;
    setTyped("");
    if (!active) return;
    playback.current?.cancel();
    // If Osky was speaking, the loop moves on to the user turn; deliver the text there.
    const deliver = () => (typedTurn.current ? typedTurn.current(text) : window.setTimeout(deliver, 50));
    deliver();
  };

  // Karaoke captions: words already spoken are bright, the current one highlighted.
  const words = useMemo(() => [...oskiText.matchAll(/\S+/g)], [oskiText]);
  const currentWord = words.findLastIndex((w) => (w.index ?? 0) <= spokenUntil);

  return (
    <div ref={root} className={`persona persona--${state} ${active ? "persona--active" : ""}`}>
      <div className="space" aria-hidden>
        <div className="space__nebula" />
        <img className="space__moon" src="/space/moon.png" alt="" draggable={false} />
        {stars.map((style, i) => (
          <div key={i} className={`space__stars space__stars--${i + 1}`} style={style} />
        ))}
        <div className="space__shooting" />
      </div>
      <div className="dust" aria-hidden>
        {Array.from({ length: 14 }, (_, i) => (
          <i key={i} style={{ left: `${(i * 37) % 100}%`, top: `${(i * 53) % 100}%`, animationDelay: `${-i * 1.7}s` }} />
        ))}
      </div>

      <div className="persona__scene">
        <button
          className={`astro astro--${state} ${active ? "astro--close" : ""}`}
          onClick={active ? interrupt : () => void start()}
          aria-label={active ? "Interrumpir a Osky" : `Hablar con ${name}`}
        >
          {/* "camera": when the conversation starts Osky flies towards you and stays
              in a close-up (helmet and chest); when it ends he drifts back */}
          <span className="astro__camera">
            <span className="astro__waves" aria-hidden>
              <i />
              <i />
              <i />
            </span>
            <span className={`astro__entrance ${entrance ? `astro__entrance--${entrance}` : ""}`}>
              <span className="astro__float">
                <OskiRig state={state} mood={state === "listening" ? "curious" : mood} gesture={gesture} />
              </span>
            </span>
            <span className="astro__orbit" aria-hidden>
              <i />
              <i />
              <i />
            </span>
          </span>
        </button>
      </div>

      <div className="captions" aria-live="polite">
        {userText && state !== "idle" && (
          <p className={`captions__user ${state === "listening" ? "captions__user--live" : ""}`}>
            <span>{visitorName ?? "Tú"}:</span> {userText}
          </p>
        )}
        {oskiText && (state === "speaking" || state === "idle") && (
          <p className="captions__oski">
            {words.map((w, i) => (
              <span key={i} className={i < currentWord ? "w w--said" : i === currentWord ? "w w--now" : "w"}>
                {w[0]}{" "}
              </span>
            ))}
          </p>
        )}
        {state !== "listening" && <SourceLabel source={source} className="captions__source" />}
        {/* WhatsApp buttons stay visible while Osky listens, so they can be tapped. */}
        <ActionButtons actions={actions} conversationId={conversationId.current} />
      </div>

      <div className="persona__controls">
        {!active ? (
          <>
            <button className="persona__start" onClick={() => void start()}>
              Hablar con {name}
            </button>
            {!canListen && !canRecord && (
              <p className="persona__hint">Tu navegador no permite usar el micrófono: escribe tu pregunta.</p>
            )}
          </>
        ) : (
          <div className="persona__bar">
            <span className={`persona__status persona__status--${state}`}>
              {state === "listening" ? (
                <span className="mic-meter" aria-hidden>
                  <i />
                  <i />
                  <i />
                  <i />
                  <i />
                </span>
              ) : (
                <i />
              )}{" "}
              {state === "listening" ? LISTEN_STATUS[phase] : STATUS[state]}
            </span>
            <form className="persona__type" onSubmit={onType}>
              <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="…o escribe aquí" aria-label="Escribir a Osky" />
            </form>
            <button className="persona__end" onClick={end}>
              Terminar
            </button>
          </div>
        )}
        {error && <p className="persona__error">{error}</p>}
      </div>
    </div>
  );
}
