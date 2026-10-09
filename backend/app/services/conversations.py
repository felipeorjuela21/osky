"""Conversations with visitors: their name, and a log of every question/answer.

Osky asks for the visitor's name first, then uses it in the conversation. Each
conversation (name + date/time) and its messages are stored so CeluWeb can review
what people ask (admin page / CSV export).
"""
import csv
import io
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Engine

from backend.app.core.config import settings
from backend.app.core.db import chat_messages, conversations

COLOMBIA = timezone(timedelta(hours=-5))  # Colombia has no daylight saving time

def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))

# ---------- the visitor's name ----------

LEADING = [
    "hola", "holi", "buenas", "buenos dias", "buenas tardes", "buenas noches", "hey", "bueno", "pues", "claro",
    "si", "ok", "listo", "osky", "oski", "mucho gusto", "un gusto", "encantado", "encantada",
]
INTROS = [
    "me llamo", "mi nombre es", "mi nombre", "yo soy", "soy", "te habla", "habla", "puedes llamarme",
    "puedes decirme", "llamame", "dime", "me dicen", "con",
]
# Words that mean this is not a name (a question, a request, a product...).
NOT_NAME = set(
    """que como cual cuanto cuantos cuanta donde cuando quien porque para por quiero necesito busco tienen tiene hay
    precio precios cotizar asesor asesores informacion ayuda gracias no nada nadie prefiero anonimo celuweb tms pricing
    chat bot whatsapp empresa servicio servicios solucion soluciones hablar saber conocer contacto telefono correo
    bien mal hoy aqui alli esto eso este esta el la los las un una unos unas mi tu su es son ser estoy""".split()
)
CONNECTORS = {"de", "del", "y", "la", "las", "los"}
DECLINE = re.compile(r"\b(prefiero no|no quiero|no te (lo )?digo|anonim[oa]|no importa|sin nombre|no deseo)\b")

def extract_name(text: str) -> str | None:
    """'Me llamo juan felipe' -> 'Juan Felipe'. None if the text is not a name."""
    if "?" in text or "¿" in text:
        return None
    words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", text)
    plain = [_plain(w) for w in words]

    def strip_phrases(phrases: list[str]) -> bool:
        joined = " ".join(plain)
        for phrase in sorted(phrases, key=len, reverse=True):
            if joined == phrase or joined.startswith(phrase + " "):
                n = len(phrase.split())
                del words[:n], plain[:n]
                return True
        return False

    while plain and strip_phrases(LEADING):
        pass
    strip_phrases(INTROS)
    if not words or len(words) > 4:
        return None
    name: list[str] = []
    for word, p in zip(words, plain):
        if p in CONNECTORS and name:
            break  # "Juan de la Cruz" -> "Juan"
        if p in NOT_NAME or len(word) < 2:
            return None
        if len(name) < 2:
            name.append(word.capitalize())
    return " ".join(name) or None

def name_reply(text: str, attempt: int) -> dict:
    """What Osky says after asking the name. status: ok | retry | declined | skip."""
    name = extract_name(text)
    if name:
        return {"status": "ok", "name": name,
                "reply": f"¡Mucho gusto, {name}! ¿En qué te puedo ayudar hoy?"}
    if DECLINE.search(_plain(text)):
        return {"status": "declined", "name": None,
                "reply": "No hay problema. ¿En qué te puedo ayudar hoy?"}
    if attempt <= 1:
        return {"status": "retry", "name": None,
                "reply": "Perdona, no te entendí el nombre. ¿Cómo te llamas?"}
    return {"status": "skip", "name": None, "reply": "No hay problema, sigamos."}

def personalize(answer: str, name: str | None, intent: str, ack: str) -> str:
    """Adds the visitor's name naturally: '¡Con gusto, Ana!', 'Mira, Ana. TMS: ...'."""
    if not name:
        return answer
    match = re.match(r"^¡([^!]{1,40})!", answer)
    if match:
        return f"¡{match.group(1)}, {name}!{answer[match.end():]}"
    if answer.startswith("Mmm, "):
        return f"Mmm, {name}, {answer[5:]}"
    if intent == "answer":
        return f"{ack}, {name}. {answer}"
    return answer

# ---------- storage ----------

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # stored as naive UTC

def start(engine: Engine, channel: str, user_agent: str = "") -> str:
    conversation_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(insert(conversations).values(
            id=conversation_id, channel=channel, started_at=_now(), last_activity_at=_now(),
            questions=0, user_agent=user_agent[:200],
        ))
    return conversation_id

def get(engine: Engine, conversation_id: str | None) -> dict | None:
    if not conversation_id:
        return None
    with engine.connect() as conn:
        row = conn.execute(select(conversations).where(conversations.c.id == conversation_id)).first()
    return dict(row._mapping) if row else None

def set_name(engine: Engine, conversation_id: str, name: str) -> None:
    with engine.begin() as conn:
        conn.execute(update(conversations).where(conversations.c.id == conversation_id).values(visitor_name=name))

def log_message(engine: Engine, conversation_id: str, role: str, text: str,
                intent: str | None = None, source: str | None = None, is_question: bool = False) -> None:
    with engine.begin() as conn:
        conn.execute(insert(chat_messages).values(
            conversation_id=conversation_id, created_at=_now(), role=role, text=text, intent=intent, source=source,
        ))
        values = {"last_activity_at": _now()}
        if is_question:
            values["questions"] = conversations.c.questions + 1
        conn.execute(update(conversations).where(conversations.c.id == conversation_id).values(**values))

def recent_questions(engine: Engine, conversation_id: str, limit: int = 3) -> list[str]:
    """Last questions the visitor asked (oldest first), for the advisor's WhatsApp message."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(chat_messages.c.text).where(
                chat_messages.c.conversation_id == conversation_id, chat_messages.c.role == "visitante",
                (chat_messages.c.intent.is_(None)) | (chat_messages.c.intent != "nombre"),
            ).order_by(chat_messages.c.id.desc()).limit(limit)
        ).scalars().all()
    return list(reversed(rows))

# ---------- admin views ----------

def _iso(dt: datetime | None) -> str | None:
    return dt.replace(tzinfo=timezone.utc).isoformat() if dt else None

def _local(dt: datetime | None) -> str:
    return dt.replace(tzinfo=timezone.utc).astimezone(COLOMBIA).strftime("%Y-%m-%d %H:%M:%S") if dt else ""

def list_conversations(engine: Engine, limit: int = 50, offset: int = 0, search: str = "") -> dict:
    with engine.connect() as conn:
        query = select(conversations).where(conversations.c.questions > 0)
        if search:
            query = query.where(func.lower(conversations.c.visitor_name).contains(search.lower(), autoescape=True))
        total = conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
        rows = conn.execute(query.order_by(conversations.c.started_at.desc()).limit(limit).offset(offset)).all()
        items = []
        for r in rows:
            last = conn.execute(
                select(chat_messages.c.text).where(chat_messages.c.conversation_id == r.id, chat_messages.c.role == "visitante")
                .order_by(chat_messages.c.id.desc()).limit(1)
            ).scalar_one_or_none()
            items.append({
                "id": r.id, "name": r.visitor_name or "Sin nombre", "channel": r.channel,
                "started_at": _iso(r.started_at), "last_activity_at": _iso(r.last_activity_at),
                "questions": r.questions, "last_question": last,
            })
    return {"total": total, "items": items}

def transcript(engine: Engine, conversation_id: str) -> dict | None:
    conversation = get(engine, conversation_id)
    if not conversation:
        return None
    with engine.connect() as conn:
        rows = conn.execute(
            select(chat_messages).where(chat_messages.c.conversation_id == conversation_id).order_by(chat_messages.c.id)
        ).all()
    return {
        "id": conversation_id,
        "name": conversation["visitor_name"] or "Sin nombre",
        "channel": conversation["channel"],
        "started_at": _iso(conversation["started_at"]),
        "messages": [
            {"at": _iso(r.created_at), "role": r.role, "text": r.text, "intent": r.intent, "source": r.source}
            for r in rows
        ],
    }

def export_csv(engine: Engine) -> str:
    """Every message with its conversation's name; times in Colombia (UTC-5). Excel-friendly."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(
                conversations.c.id, conversations.c.visitor_name, conversations.c.channel, conversations.c.started_at,
                chat_messages.c.created_at, chat_messages.c.role, chat_messages.c.text, chat_messages.c.intent,
                chat_messages.c.source,
            )
            .join(chat_messages, chat_messages.c.conversation_id == conversations.c.id)
            .order_by(conversations.c.started_at, chat_messages.c.id)
        ).all()
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow(["conversacion", "nombre", "canal", "inicio (hora Colombia)", "hora mensaje", "quien", "mensaje", "tipo", "fuente"])
    for r in rows:
        writer.writerow([
            r.id, r.visitor_name or "Sin nombre", r.channel, _local(r.started_at), _local(r.created_at),
            settings.agent_name if r.role == "osky" else "Visitante", r.text, r.intent or "", r.source or "",
        ])
    return "﻿" + out.getvalue()  # BOM so Excel shows accents correctly
