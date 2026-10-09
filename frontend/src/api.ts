export type Source = { title: string; url: string; kind: string; score: number };
export type Action = { type: "whatsapp"; label: string; url: string; contact: string; area: string };

export type AskResponse = {
  status: "ok" | "not_found" | "not_understood" | "rejected";
  source: "website" | "database" | "persona" | null;
  intent: "answer" | "not_found" | "sales" | "greeting" | "how_are_you" | "identity" | "help" | "thanks" | "goodbye";
  answer: string;
  /** Rest of the answer when style is "voice" (offered with "¿te cuento más?"). */
  more?: string;
  sources: Source[];
  /** Buttons to show with the answer, e.g. WhatsApp of a sales advisor. */
  actions?: Action[];
  /** Visitor's name, when the conversation has one. */
  name?: string | null;
};

export type NameResult = { status: "ok" | "retry" | "declined" | "skip"; name: string | null; reply: string };

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
export const ask = (question: string, style: "chat" | "voice" = "chat", topic?: string | null, conversationId?: string | null) =>
  post<AskResponse>("/api/ask", {
    question,
    style,
    topic: topic || undefined,
    conversation_id: conversationId || undefined,
  });

/* ---------- conversations: Osky asks the name first and every chat is logged ---------- */

export const startConversation = (channel: "chat" | "persona") =>
  post<{ id: string; greeting: string }>("/api/conversations", { channel });

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
};
export type Transcript = {
  id: string;
  name: string;
  channel: string;
  started_at: string;
  messages: { at: string; role: "visitante" | "osky"; text: string; intent: string | null; source: string | null }[];
};

export class AdminAuthError extends Error {}

async function adminFetch(path: string, token: string): Promise<Response> {
  const response = await fetch(apiUrl(path), { headers: token ? { "X-Admin-Token": token } : {} });
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
