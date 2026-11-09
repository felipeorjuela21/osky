export type Source = { title: string; url: string; kind: string; score: number };
export type Advisor = { name: string; area: string; photo: string; solutions: string[]; url: string };
export type Action = {
  type: "whatsapp";
  label: string;
  url: string;
  contact: string;
  area: string;
  /** Advisors to choose from (up to 3); each link already carries the conversation summary. */
  advisors?: Advisor[];
};

export type AskResponse = {
  status: "ok" | "not_found" | "not_understood" | "rejected" | "blocked";
  source: "website" | "database" | "persona" | null;
  intent: "answer" | "not_found" | "sales" | "greeting" | "how_are_you" | "identity" | "help" | "thanks" | "goodbye" | "blocked";
  answer: string;
  /** Rest of the answer when style is "voice" (offered with "¿te cuento más?"). */
  more?: string;
  sources: Source[];
  /** Buttons to show with the answer, e.g. WhatsApp of a sales advisor. */
  actions?: Action[];
  /** Visitor's name, when the conversation has one. */
  name?: string | null;
  /** true: Osky closed the conversation (offensive language); no more turns. */
  ended?: boolean;
};

/** A previous question and answer, so follow-ups ("¿y eso cuánto cuesta?") are understood. */
export type Turn = { q: string; a: string };

export type NameResult = { status: "ok" | "retry" | "declined" | "skip" | "blocked"; name: string | null; reply: string; ended?: boolean };

export type AgentInfo = {
  name: string;
  company: string;
  website: string;
  greeting: string;
};

/** Backend URL. Empty in development (Vite proxies /api); in production the
    Cloudflare Pages build sets VITE_API_URL=https://<servicio>.onrender.com */
export const API_BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");
export const apiUrl = (path: string) => `${API_BASE}${path}`;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), init);
  if (!response.ok) throw new Error(`Error ${response.status} en ${path}`);
  return response.json() as Promise<T>;
}

export const getAgent = () => request<AgentInfo>("/api/agent");

const post = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

/** topic: subject of the previous answer, so "quiero cotizar" reaches the right advisor.
    conversationId: personalises with the visitor's name and logs the turn. */
export const ask = (
  question: string,
  style: "chat" | "voice" = "chat",
  topic?: string | null,
  conversationId?: string | null,
  history: Turn[] = [],
) =>
  post<AskResponse>("/api/ask", {
    question,
    style,
    topic: topic || undefined,
    conversation_id: conversationId || undefined,
    history: history.slice(-3).map((t) => ({ q: t.q.slice(0, 500), a: t.a.slice(0, 2000) })),
  });

export type AskMeta = Pick<AskResponse, "status" | "source" | "intent" | "sources" | "actions" | "ended" | "name">;

/** Same as ask(), but the answer arrives sentence by sentence (voice persona):
    onMeta first (intent, sources, WhatsApp buttons), then onSentence for each sentence
    as the model writes it. Resolves with the full response. */
export async function askStream(
  question: string,
  handlers: { onMeta?: (meta: AskMeta) => void; onSentence?: (text: string) => void },
  topic?: string | null,
  conversationId?: string | null,
  history: Turn[] = [],
): Promise<AskResponse> {
  const body = {
    question,
    style: "voice",
    topic: topic || undefined,
    conversation_id: conversationId || undefined,
    history: history.slice(-3).map((t) => ({ q: t.q.slice(0, 500), a: t.a.slice(0, 2000) })),
  };
  const response = await fetch(apiUrl("/api/ask/stream"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (response.status === 404 || response.status === 405 || !response.body) {
    // Older backend without streaming: one piece.
    const full = await ask(question, "voice", topic, conversationId, history);
    handlers.onMeta?.(full);
    handlers.onSentence?.(full.answer);
    return full;
  }
  if (!response.ok) throw new Error(`Error ${response.status} en /api/ask/stream`);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let done: AskResponse | null = null;
  const handle = (line: string) => {
    if (!line.trim()) return;
    const event = JSON.parse(line) as { type: string; text?: string } & AskResponse;
    if (event.type === "meta") handlers.onMeta?.(event);
    else if (event.type === "sentence" && event.text) handlers.onSentence?.(event.text);
    else if (event.type === "done") done = event;
  };
  for (;;) {
    const { value, done: finished } = await reader.read();
    if (value) buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    lines.forEach(handle);
    if (finished) break;
  }
  handle(buffer);
  if (!done) throw new Error("La respuesta se cortó");
  return done;
}

/* ---------- conversations: Osky asks the name first and every chat is logged ---------- */

export const startConversation = (channel: "chat" | "persona") =>
  post<{ id: string; greeting: string; privacy_url: string }>("/api/conversations", { channel });

export const sendName = (conversationId: string, text: string, attempt: number) =>
  post<NameResult>(`/api/conversations/${conversationId}/name`, { text, attempt });

/** Logs a turn answered in the page itself (e.g. "¿Te cuento más?" -> "sí"). Never blocks the chat. */
export const logTurn = (conversationId: string | null, question: string, answer: string, intent?: string) => {
  if (!conversationId) return;
  void post(`/api/conversations/${conversationId}/log`, { question, answer, intent }).catch(() => undefined);
};

/* ---------- admin (conversation log) ---------- */

export type ConversationSummary = {
  id: string;
  name: string;
  channel: string;
  started_at: string;
  last_activity_at: string;
  questions: number;
  last_question: string | null;
  ended_reason?: string | null;
};
export type Transcript = {
  id: string;
  name: string;
  channel: string;
  started_at: string;
  consent_at?: string | null;
  policy_version?: string | null;
  ended_reason?: string | null;
  messages: { at: string; role: "visitante" | "osky"; text: string; intent: string | null; source: string | null }[];
};

export class AdminAuthError extends Error {}

async function adminFetch(path: string, token: string, method = "GET"): Promise<Response> {
  const response = await fetch(apiUrl(path), { method, headers: token ? { "X-Admin-Token": token } : {} });
  if (response.status === 401 || response.status === 403) throw new AdminAuthError(await response.text());
  if (!response.ok) throw new Error(`Error ${response.status}`);
  return response;
}

export const adminConversations = async (token: string, offset = 0, q = "") =>
  (await adminFetch(`/api/admin/conversations?limit=50&offset=${offset}&q=${encodeURIComponent(q)}`, token)).json() as Promise<{
    total: number;
    items: ConversationSummary[];
  }>;

export const adminTranscript = async (token: string, id: string) =>
  (await adminFetch(`/api/admin/conversations/${id}`, token)).json() as Promise<Transcript>;

/** Right to deletion: removes the conversation and all its messages. */
export const adminDelete = async (token: string, id: string) => {
  await adminFetch(`/api/admin/conversations/${id}`, token, "DELETE");
};

export const adminExportCsv = async (token: string) => (await adminFetch("/api/admin/export.csv", token)).blob();

/** Topic to remember from an answer: the solution it was about, if any. */
export const topicOf = (r: AskResponse) => (r.sources[0]?.kind === "servicio" ? r.sources[0].title : null);

/** Wakes the backend up (the free server sleeps after 15 min without visits). */
export async function waitForBackend(onSlow: () => void, timeoutMs = 90000): Promise<boolean> {
  const slow = window.setTimeout(onSlow, 2500);
  const deadline = Date.now() + timeoutMs;
  try {
    while (Date.now() < deadline) {
      try {
        const response = await fetch(apiUrl("/health"), { cache: "no-store" });
        if (response.ok) return true;
      } catch {
        /* still waking up */
      }
      await new Promise((r) => window.setTimeout(r, 2000));
    }
    return false;
  } finally {
    window.clearTimeout(slow);
  }
}

/** Logs which advisor the visitor chose in the WhatsApp picker. Never blocks the page. */
export const logContact = (conversationId: string | null | undefined, advisor: string) => {
  if (!conversationId) return;
  void post(`/api/conversations/${conversationId}/contact`, { advisor }).catch(() => undefined);
};
