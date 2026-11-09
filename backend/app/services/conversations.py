"""Conversations with visitors: their name, and a log of every question/answer.

Osky first tells the visitor that the conversation is stored under CeluWeb's data
policy and asks their name: giving it is their authorisation (Ley 1581 de 2012,
Decreto 1377 de 2013 art. 7, "conducta inequívoca"). Only then are the name and the
messages stored (admin page / CSV export). If they decline, nothing is stored.
Stored conversations are deleted after DATA_RETENTION_DAYS.
"""
import csv
import io
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, insert, select, update
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
    if DECLINE.search(_plain(text)) or re.fullmatch(r"\W*(no|nop|nel|no gracias)\W*", _plain(text)):
        return {"status": "declined", "name": None,
                "reply": "No hay problema, no guardaré nada de esta conversación. ¿En qué te puedo ayudar?"}
    if attempt <= 1:
        return {"status": "retry", "name": None,
                "reply": "Perdona, no te entendí el nombre. ¿Cómo te llamas?"}
    return {"status": "skip", "name": None, "reply": "No hay problema, sigamos sin guardar tus datos."}

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

OPENERS = re.compile(r"^(claro|mira|perfecto|bueno|genial|excelente|listo|con gusto|te cuento|por supuesto|s[ií])([,.]\s*)", re.I)

def add_name(answer: str, name: str) -> str:
    """Name in a model-written answer: '¡Claro! ...' -> '¡Claro, Ana! ...', 'Mira, ...' -> 'Mira, Ana, ...'."""
    match = re.match(r"^¡([^!]{1,40})!", answer)
    if match:
        return f"¡{match.group(1)}, {name}!{answer[match.end():]}"
    match = OPENERS.match(answer)
    if match:
        sep = ". " if "." in match.group(2) else ", "
        return f"{match.group(1)}, {name}{sep}{answer[match.end():]}"
    first = answer.split(" ", 1)[0]
    keep_case = not first[1:].islower() or first.lower() in {settings.company_name.lower(), settings.agent_name.lower()}
    return f"{name}, {answer if keep_case else answer[:1].lower() + answer[1:]}"

# ---------- storage ----------

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # stored as naive UTC

def start(engine: Engine, channel: str) -> str:
    """A new conversation, still without consent: nothing personal is stored yet."""
    purge_expired(engine)
    conversation_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(insert(conversations).values(
            id=conversation_id, channel=channel, started_at=_now(), last_activity_at=_now(), questions=0,
        ))
    return conversation_id

def has_consent(conversation: dict | None) -> bool:
    return bool(conversation) and conversation.get("consent") == "si"

def is_closed(conversation: dict | None) -> bool:
    return bool(conversation) and bool(conversation.get("ended_reason"))

def accept(engine: Engine, conversation_id: str, name: str, user_agent: str = "") -> None:
    """The visitor gave their name after the data notice: authorisation recorded."""
    with engine.begin() as conn:
        conn.execute(update(conversations).where(conversations.c.id == conversation_id).values(
            visitor_name=name, consent="si", consent_at=_now(), policy_version=settings.privacy_policy_version,
            user_agent=user_agent[:200],
        ))

def decline(engine: Engine, conversation_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(update(conversations).where(conversations.c.id == conversation_id).values(
            consent="no", consent_at=_now(), policy_version=settings.privacy_policy_version,
        ))

def close(engine: Engine, conversation_id: str, reason: str) -> None:
    """Osky ends the conversation (e.g. offensive language): no more turns are answered."""
    with engine.begin() as conn:
        conn.execute(update(conversations).where(conversations.c.id == conversation_id).values(
            ended_reason=reason, last_activity_at=_now(),
        ))

def remove(engine: Engine, conversation_id: str) -> bool:
    """Deletes a conversation and its messages (the visitor's right to deletion)."""
    with engine.begin() as conn:
        conn.execute(delete(chat_messages).where(chat_messages.c.conversation_id == conversation_id))
        return conn.execute(delete(conversations).where(conversations.c.id == conversation_id)).rowcount > 0

_last_purge: dict = {"at": None}

def purge_expired(engine: Engine, days: int | None = None, force: bool = False) -> int:
    """Deletes conversations older than the retention period (checked at most once an hour)."""
    days = settings.data_retention_days if days is None else days
    now = _now()
    if days <= 0 or (not force and _last_purge["at"] and now - _last_purge["at"] < timedelta(hours=1)):
        return 0
    _last_purge["at"] = now
    cutoff = now - timedelta(days=days)
    with engine.begin() as conn:
        old = select(conversations.c.id).where(conversations.c.last_activity_at < cutoff)
        conn.execute(delete(chat_messages).where(chat_messages.c.conversation_id.in_(old)))
        return conn.execute(delete(conversations).where(conversations.c.last_activity_at < cutoff)).rowcount

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
                "questions": r.questions, "last_question": last, "ended_reason": r.ended_reason,
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
        "consent_at": _iso(conversation["consent_at"]),
        "policy_version": conversation["policy_version"],
        "ended_reason": conversation["ended_reason"],
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
