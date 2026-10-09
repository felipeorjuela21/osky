import random
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from backend.app.core.config import settings
from backend.app.core.data_dictionary import DATA_DICTIONARY
from backend.app.core.db import engine
from backend.app.core.security import rate_limit, require_admin
from backend.app.services import conversations
from backend.app.services.answer import build_answer
from backend.app.services.knowledge import answer_from_knowledge, knowledge_stats, split_for_voice
from backend.app.services.llm import natural_answer
from backend.app.services.stt import STTUnavailable, transcribe
from backend.app.services.tts import TTSUnavailable, allowed_voice, spanish_voices, synthesize
from backend.app.services.sales import SOLUTIONS, detect_solution, is_sales_request, whatsapp_action
from backend.app.services.smalltalk import match_smalltalk, strip_greeting
from backend.app.services.nl_parser import NotUnderstood, load_known_values, parse_question
from backend.app.services.query_engine import (
    QueryAST,
    average_field,
    count_records,
    execute_query,
    list_datasets,
    log_query,
    recent_logs,
    sum_field,
)

router = APIRouter(prefix="/api")

HELP_TEXT = (
    f"Respondo solo con información oficial de {settings.company_name}. "
    "Puedes preguntarme por nuestras soluciones, como TMS, Pricing, Chat Bot o Fuerza de Ventas, "
    "por nuestra misión y visión, o pedirme hablar con un asesor comercial por WhatsApp."
)

class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    # "voice": short spoken answer, the rest is returned in "more".
    style: Literal["chat", "voice"] = "chat"
    # Topic of the previous answer (e.g. "TMS"), so "quiero cotizar" goes to the right advisor.
    topic: str | None = Field(default=None, max_length=120)
    # Conversation with the visitor: personalises with their name and logs the turn.
    conversation_id: str | None = Field(default=None, max_length=36)

ACKS = ["Claro", "Mira", "Te cuento", "Con gusto"]

class StartConversation(BaseModel):
    channel: Literal["chat", "persona"] = "chat"

class NameRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=120)
    attempt: int = Field(default=1, ge=1, le=5)

class LogTurn(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    answer: str = Field(..., min_length=1, max_length=2000)
    intent: str | None = Field(default=None, max_length=30)

@router.get("/agent")
def agent():
    return {
        "name": settings.agent_name,
        "company": settings.company_name,
        "website": settings.website_url,
        "greeting": f"¡Hola! Soy {settings.agent_name}, el asistente virtual de {settings.company_name}. {HELP_TEXT}",
        "demo_data": settings.enable_demo_data,
        "tts": {"provider": settings.effective_tts, "voice": settings.tts_voice},
        "stt": {"provider": settings.effective_stt},
        "llm": {"provider": settings.effective_llm},
    }

class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1500)
    voice: str | None = Field(default=None, pattern=r"^[a-z]{2}-[A-Z]{2}-[A-Za-z]+Neural$")
    rate: str | None = Field(default=None, pattern=r"^[+-]\d{1,2}%$")

@router.post("/tts", dependencies=[Depends(rate_limit)])
async def tts(request: TTSRequest):
    try:
        return await synthesize(request.text, await allowed_voice(request.voice), request.rate)
    except TTSUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"TTS no disponible: {exc}")

@router.get("/tts/voices")
async def tts_voices():
    try:
        return {"default": settings.tts_voice, "voices": await spanish_voices()}
    except TTSUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"TTS no disponible: {exc}")

MAX_AUDIO_BYTES = 8 * 1024 * 1024

@router.post("/stt", dependencies=[Depends(rate_limit)])
async def stt(request: Request):
    """Body: the recorded audio (webm/ogg/wav). Returns {"text": ..., "duration": ...}."""
    audio = await request.body()
    if not audio:
        raise HTTPException(status_code=400, detail="Audio vacío")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio demasiado largo")
    try:
        content_type = request.headers.get("content-type", "audio/webm")
        return await run_in_threadpool(transcribe, audio, content_type)
    except STTUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Reconocimiento de voz no disponible: {exc}")

@router.get("/knowledge")
def knowledge():
    return {"source": settings.website_url, **knowledge_stats(engine)}

@router.post("/knowledge/refresh", dependencies=[Depends(require_admin)])
def knowledge_refresh():
    from backend.scripts.ingest_website import ingest

    try:
        chunks = ingest(engine)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo leer {settings.website_url}: {exc}")
    return {"status": "ok", "chunks": chunks}

@router.get("/datasets")
def datasets():
    return {"datasets": list_datasets(engine)}

@router.get("/dictionary")
def dictionary():
    return {
        name: {
            "operations": sorted(spec["operations"]),
            "fields": {f: {"type": s["type"], "label": s["label"]} for f, s in spec["fields"].items()},
        }
        for name, spec in DATA_DICTIONARY.items()
    }

@router.post("/query")
def structured_query(ast: QueryAST):
    try:
        result = execute_query(engine, ast)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    answer = build_answer(ast, result)
    log_query(engine, None, ast, answer, "ok")
    return {"source": "database", "query": ast.model_dump(), "result": result, "answer": answer}

@router.post("/conversations", dependencies=[Depends(rate_limit)])
def start_conversation(body: StartConversation, request: Request):
    """Starts a chat: Osky greets and asks the visitor's name first."""
    conversation_id = conversations.start(engine, body.channel, request.headers.get("user-agent", ""))
    greeting = (f"¡Hola! Soy {settings.agent_name}, el asistente virtual de {settings.company_name}. "
                "Antes de empezar, ¿cómo te llamas? Así te atiendo de forma más personal.")
    return {"id": conversation_id, "greeting": greeting}

@router.post("/conversations/{conversation_id}/name", dependencies=[Depends(rate_limit)])
def conversation_name(conversation_id: str, body: NameRequest):
    if not conversations.get(engine, conversation_id):
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    result = conversations.name_reply(body.text, body.attempt)
    if result["name"]:
        conversations.set_name(engine, conversation_id, result["name"])
    conversations.log_message(engine, conversation_id, "visitante", body.text, intent="nombre")
    conversations.log_message(engine, conversation_id, "osky", result["reply"], intent="nombre")
    return result

@router.post("/conversations/{conversation_id}/log", dependencies=[Depends(rate_limit)])
def conversation_log(conversation_id: str, body: LogTurn):
    """Turns answered in the page itself (e.g. "¿Te cuento más?" -> "sí")."""
    if not conversations.get(engine, conversation_id):
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    conversations.log_message(engine, conversation_id, "visitante", body.question, is_question=True)
    conversations.log_message(engine, conversation_id, "osky", body.answer, intent=body.intent)
    return {"status": "ok"}

@router.get("/admin/conversations", dependencies=[Depends(require_admin)])
def admin_conversations(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), q: str = ""):
    return conversations.list_conversations(engine, limit, offset, q.strip())

@router.get("/admin/conversations/{conversation_id}", dependencies=[Depends(require_admin)])
def admin_conversation(conversation_id: str):
    result = conversations.transcript(engine, conversation_id)
    if not result:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    return result

@router.get("/admin/export.csv", dependencies=[Depends(require_admin)])
def admin_export():
    filename = f"osky-conversaciones-{datetime.now():%Y%m%d}.csv"
    return Response(
        conversations.export_csv(engine), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@router.post("/ask", dependencies=[Depends(rate_limit)])
def ask(request: AskRequest):
    conversation = conversations.get(engine, request.conversation_id)
    name = conversation["visitor_name"] if conversation else None
    response = _answer(request, name)

    # Warm, personal wording: "Claro, Ana. TMS: ..." (natural answers already include it).
    if not response.pop("_natural", False):
        ack = random.choice(ACKS)
        if name:
            response["answer"] = conversations.personalize(response["answer"], name, response["intent"], ack)
        elif request.style == "voice" and response["intent"] == "answer":
            response["answer"] = f"{ack}. {response['answer']}"

    # Log the turn in the visitor's conversation.
    if conversation:
        parts = []
        if response.get("sources"):
            parts.append(response["sources"][0]["title"])
        if response.get("actions"):
            parts.append(f"WhatsApp → {response['actions'][0]['contact']}")
        source = " · ".join(parts) or None
        conversations.log_message(engine, conversation["id"], "visitante", request.question, is_question=True)
        conversations.log_message(engine, conversation["id"], "osky", response["answer"], response["intent"], source)
    response["name"] = name
    return response

def _answer(request: AskRequest, name: str | None) -> dict:
    question = request.question

    # 0. Conversation (hola, gracias, adiós...): fixed replies about Osky, no company data.
    talk = match_smalltalk(question)
    if talk:
        log_query(engine, question, None, talk["answer"], f"smalltalk:{talk['intent']}")
        return {"status": "ok", "source": "persona", "intent": talk["intent"], "answer": talk["answer"],
                "query": None, "result": None, "sources": [], "actions": []}
    question = strip_greeting(question)

    # 1. Wants an advisor, a quote or prices -> WhatsApp of the sales team.
    if is_sales_request(question):
        solution = detect_solution(question, request.topic)
        action = whatsapp_action(solution)
        if action:
            about = f" sobre {solution}" if solution else ""
            if request.style == "voice":
                answer = (f"¡Con gusto! Te dejo en pantalla el botón para escribirle por WhatsApp a {action['contact']}, "
                          f"que te atenderá personalmente{about}.")
            else:
                answer = (f"¡Con gusto! Te comunico por WhatsApp con {action['contact']}"
                          f"{' (' + action['area'] + ')' if action['area'] else ''} para que te atienda personalmente{about}. "
                          "Toca el botón de abajo y el mensaje ya va escrito.")
            actions = [action]
        else:
            answer = ("En este momento no tengo un asesor configurado para WhatsApp. "
                      "Puedes escribir a contacto@celuweb.com y te atenderán.")
            actions = []
        log_query(engine, question, None, answer, "sales")
        return {"status": "ok", "source": "sales", "intent": "sales", "answer": answer,
                "query": None, "result": None, "sources": [], "actions": actions}

    # 1. Structured enterprise data (only when real/demo tables are enabled).
    if settings.enable_demo_data:
        ast = None
        try:
            ast = parse_question(question, load_known_values(engine))
            result = execute_query(engine, ast)
            answer = build_answer(ast, result)
            log_query(engine, question, ast, answer, "ok")
            return {"status": "ok", "source": "database", "intent": "answer", "answer": answer,
                    "query": ast.model_dump(), "result": result, "sources": [], "actions": []}
        except NotUnderstood:
            pass
        except ValueError as exc:
            answer = f"No puedo ejecutar esa consulta: {exc}."
            log_query(engine, question, ast, answer, "rejected")
            return {"status": "rejected", "source": "database", "intent": "answer", "answer": answer,
                    "query": ast.model_dump() if ast else None, "result": None, "sources": [], "actions": []}

    # 2. Company website knowledge.
    found = answer_from_knowledge(engine, question)
    if found:
        # Natural wording from the same sources (Groq); literal extract as fallback.
        natural = natural_answer(question, found["context"], request.style, name)
        answer, more = (natural, "") if natural else (found["answer"], "")
        if not natural and request.style == "voice":
            answer, more = split_for_voice(answer)
        log_query(engine, question, None, answer, "ok")
        # After explaining a solution, offer a direct line to an advisor about it.
        top = found["sources"][0]
        actions = []
        if top["kind"] == "servicio":
            action = whatsapp_action(top["title"] if top["title"] in SOLUTIONS else None)
            if action:
                actions = [action]
        return {"status": "ok", "source": "website", "intent": "answer", "answer": answer, "more": more,
                "query": None, "result": None, "sources": found["sources"], "actions": actions,
                "_natural": bool(natural)}

    answer = (
        f"Mmm, eso no lo encuentro en la información oficial de {settings.company_name}, y prefiero no inventar. "
        "Puedo contarte sobre nuestras soluciones, como TMS, Pricing o Chat Bot, o darte los datos de contacto."
    )
    if request.style == "voice":
        answer = f"Mmm, eso no lo encuentro en la información de {settings.company_name} y prefiero no inventar. ¿Te cuento de nuestras soluciones?"
    log_query(engine, question, None, answer, "not_found")
    return {"status": "not_found", "source": None, "intent": "not_found", "answer": answer, "query": None,
            "result": None, "sources": [], "actions": []}

@router.get("/logs", dependencies=[Depends(require_admin)])
def logs(limit: int = Query(20, ge=1, le=200)):
    return {"logs": recent_logs(engine, limit)}

@router.get("/query/count")
def count(
    dataset: str = Query(...),
    field: str | None = None,
    value: str | None = None,
):
    try:
        result = count_records(engine, dataset, field, value)
        return {"source": "database", "operation": "count", "result": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.get("/query/sum")
def sum_query(dataset: str = Query(...), field: str = Query(...)):
    try:
        result = sum_field(engine, dataset, field)
        return {"source": "database", "operation": "sum", "result": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.get("/query/average")
def average(dataset: str = Query(...), field: str = Query(...)):
    try:
        result = average_field(engine, dataset, field)
        return {"source": "database", "operation": "average", "result": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
