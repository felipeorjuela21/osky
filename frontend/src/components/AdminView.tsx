import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  AdminAuthError,
  ConversationSummary,
  Transcript,
  adminConversations,
  adminExportCsv,
  adminTranscript,
} from "../api";
import "./admin.css";

/* Private log of conversations (open with ?admin=1). Needs ADMIN_TOKEN on the server. */

const TOKEN_KEY = "osky.adminToken";
const dateFmt = new Intl.DateTimeFormat("es-CO", { timeZone: "America/Bogota", dateStyle: "medium", timeStyle: "short" });
const timeFmt = new Intl.DateTimeFormat("es-CO", { timeZone: "America/Bogota", timeStyle: "medium" });

function storedToken(): string {
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function AdminView() {
  const [token, setToken] = useState(storedToken);
  const [tokenInput, setTokenInput] = useState("");
  const [needsToken, setNeedsToken] = useState(false);
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Transcript | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(
    async (nextOffset = 0, q = search) => {
      setLoading(true);
      setError(null);
      try {
        const data = await adminConversations(token, nextOffset, q);
        setItems(data.items);
        setTotal(data.total);
        setOffset(nextOffset);
        setNeedsToken(false);
      } catch (e) {
        if (e instanceof AdminAuthError) setNeedsToken(true);
        else setError("No pude cargar el registro. ¿Está encendido el servidor?");
      } finally {
        setLoading(false);
      }
    },
    [token, search],
  );

  useEffect(() => {
    void load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const open = async (id: string) => {
    try {
      setSelected(await adminTranscript(token, id));
    } catch {
      setError("No pude abrir la conversación.");
    }
  };

  const download = async () => {
    try {
      const blob = await adminExportCsv(token);
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `osky-conversaciones-${new Date().toISOString().slice(0, 10)}.csv`;
      link.click();
      URL.revokeObjectURL(link.href);
    } catch {
      setError("No pude descargar el archivo.");
    }
  };

  const saveToken = (e: FormEvent) => {
    e.preventDefault();
    try {
      sessionStorage.setItem(TOKEN_KEY, tokenInput.trim());
    } catch {
      /* private mode: it lasts for this page only */
    }
    setToken(tokenInput.trim());
  };

  if (needsToken) {
    return (
      <main className="admin admin--login">
        <form className="admin__card" onSubmit={saveToken}>
          <h1>Registro de conversaciones</h1>
          <p>Ingresa la clave de administrador (ADMIN_TOKEN del servidor).</p>
          <input type="password" value={tokenInput} onChange={(e) => setTokenInput(e.target.value)} autoFocus aria-label="Clave" />
          <button type="submit" disabled={!tokenInput.trim()}>
            Entrar
          </button>
        </form>
      </main>
    );
  }

  return (
    <main className="admin">
      <div className="admin__toolbar">
        <h1>Registro de conversaciones</h1>
        <form
          className="admin__search"
          onSubmit={(e) => {
            e.preventDefault();
            void load(0, search);
          }}
        >
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Buscar por nombre…" aria-label="Buscar" />
          <button type="submit">Buscar</button>
        </form>
        <button className="admin__export" onClick={() => void download()}>
          ⬇ Exportar CSV
        </button>
      </div>
      {error && <p className="error">{error}</p>}

      <div className={`admin__body ${selected ? "admin__body--detail" : ""}`}>
        <section className="admin__list" aria-busy={loading}>
          <p className="admin__count">{total} conversaciones</p>
          {items.length === 0 && !loading && <p className="admin__empty">Todavía no hay conversaciones con preguntas.</p>}
          {items.map((c) => (
            <button key={c.id} className={`admin__item ${selected?.id === c.id ? "admin__item--on" : ""}`} onClick={() => void open(c.id)}>
              <span className="admin__name">{c.name}</span>
              <span className="admin__meta">
                {dateFmt.format(new Date(c.started_at))} · {c.channel === "persona" ? "🧑‍🚀 Persona" : "💬 Chat"} · {c.questions}{" "}
                {c.questions === 1 ? "pregunta" : "preguntas"}
              </span>
              {c.last_question && <span className="admin__last">“{c.last_question}”</span>}
            </button>
          ))}
          <div className="admin__pager">
            <button disabled={offset === 0} onClick={() => void load(Math.max(0, offset - 50))}>
              ← Anteriores
            </button>
            <button disabled={offset + 50 >= total} onClick={() => void load(offset + 50)}>
              Siguientes →
            </button>
          </div>
        </section>

        {selected && (
          <section className="admin__detail">
            <button className="admin__back" onClick={() => setSelected(null)}>
              ← Volver
            </button>
            <h2>{selected.name}</h2>
            <p className="admin__meta">
              {dateFmt.format(new Date(selected.started_at))} · {selected.channel === "persona" ? "Persona" : "Chat"}
            </p>
            <ol className="admin__messages">
              {selected.messages.map((m, i) => (
                <li key={i} className={`admin__msg admin__msg--${m.role}`}>
                  <span className="admin__who">
                    {m.role === "osky" ? "Osky" : selected.name} · {timeFmt.format(new Date(m.at))}
                  </span>
                  <span className="admin__text">{m.text}</span>
                  {m.source && <span className="admin__source">{m.source}</span>}
                </li>
              ))}
            </ol>
          </section>
        )}
      </div>
    </main>
  );
}
