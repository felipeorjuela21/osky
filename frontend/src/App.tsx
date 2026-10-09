import { Suspense, lazy, useEffect, useState } from "react";
import { AgentInfo, getAgent, waitForBackend } from "./api";
import { ChatView } from "./components/ChatView";
import { VoiceSettings } from "./components/VoiceSettings";

// Persona mode is only downloaded when it is opened.
const PersonaView = lazy(() => import("./components/PersonaView").then((m) => ({ default: m.PersonaView })));
// ?admin=1: private log of conversations (names, times, questions).
const AdminView = lazy(() => import("./components/AdminView").then((m) => ({ default: m.AdminView })));
const ADMIN = new URLSearchParams(window.location.search).get("admin") === "1";

type Mode = "chat" | "persona";
// ?embed=1: shown inside the celuweb.com widget (leaves room for its close button).
const EMBED = new URLSearchParams(window.location.search).get("embed") === "1";
const MODE_KEY = "oski.mode";

function savedMode(): Mode {
  // ?modo=persona opens straight into persona mode (e.g. a kiosk screen).
  const fromUrl = new URLSearchParams(window.location.search).get("modo");
  if (fromUrl === "persona" || fromUrl === "chat") return fromUrl;
  try {
    return localStorage.getItem(MODE_KEY) === "persona" ? "persona" : "chat";
  } catch {
    return "chat";
  }
}

export default function App() {
  const [agent, setAgent] = useState<AgentInfo | null>(null);
  const [backendError, setBackendError] = useState(false);
  const [waking, setWaking] = useState(false);
  const [mode, setMode] = useState<Mode>(savedMode);

  useEffect(() => {
    // The free server sleeps when nobody uses it; show a friendly note while it wakes up.
    void waitForBackend(() => setWaking(true)).then((up) => {
      setWaking(false);
      if (!up) return setBackendError(true);
      getAgent()
        .then(setAgent)
        .catch(() => setBackendError(true));
    });
  }, []);

  const changeMode = (next: Mode) => {
    setMode(next);
    try {
      localStorage.setItem(MODE_KEY, next);
    } catch {
      /* private mode: the choice just isn't remembered */
    }
  };

  return (
    <div className={`app app--${mode} ${EMBED ? "app--embed" : ""}`}>
      <header className="topbar">
        <div className="brand">
          <img className="brand__logo" src="/celuweb-logo.png" alt="CeluWeb" />
          <div className="brand__text">
            <span className="brand__name">{agent?.name ?? "Osky"}</span>
            <span className="brand__sub">Asistente virtual de {agent?.company ?? "CeluWeb"}</span>
          </div>
        </div>
        {!ADMIN && (
          <div className="topbar__actions">
            <VoiceSettings />
            <div className="modes" role="tablist" aria-label="Modo">
              <button role="tab" aria-selected={mode === "chat"} className={mode === "chat" ? "modes__on" : ""} onClick={() => changeMode("chat")}>
                <span aria-hidden>💬</span>
                <span className="modes__label">Chat</span>
              </button>
              <button role="tab" aria-selected={mode === "persona"} className={mode === "persona" ? "modes__on" : ""} onClick={() => changeMode("persona")}>
                <span aria-hidden>🧑‍🚀</span>
                <span className="modes__label">Persona</span>
              </button>
            </div>
          </div>
        )}
      </header>

      {waking && (
        <p className="wake-banner" role="status">
          <span className="wake-banner__dot" aria-hidden /> Despertando a Osky… la primera visita puede tardar hasta un minuto.
        </p>
      )}
      {backendError && (
        <p className="error">No pude conectarme con el servidor de Osky. Recarga la página en un momento.</p>
      )}

      {/* Switching modes unmounts the other view, which stops its audio and microphone. */}
      {ADMIN ? (
        <Suspense fallback={<p className="hint">Cargando registro…</p>}>
          <AdminView />
        </Suspense>
      ) : mode === "chat" ? (
        <ChatView agent={agent} />
      ) : (
        <Suspense fallback={<p className="hint">Cargando modo persona…</p>}>
          <PersonaView agent={agent} />
        </Suspense>
      )}
    </div>
  );
}
