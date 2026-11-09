"""Offensive language filter: an insult, obscenity or sexual content ends the conversation.

Runs before anything else (no LLM call, no search), on every text the visitor sends:
the name, each question and the follow-up turns. Words are matched as whole words
after normalising accents, leetspeak ("h1jueput4") and stretched letters
("putaaaa"), so "computadora" or "disputa" never match.

Extra words can be added without touching code in config/lenguaje_bloqueado.json
("bloquear"), and false positives can be allowed there too ("permitir").
"""
import json
import re
import unicodedata
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "lenguaje_bloqueado.json"

# Regex stems (on normalised text). Each one is matched as a whole word.
PATTERNS = [
    # Colombian / Latin American insults
    r"(h|j)?ij?[oue]e?\s?(de\s?(su|tu)?\s?)?put[ao]s?", r"hpt[ao]s?", r"jueput[ao]s?", r"ptm",
    r"put[ao]s?", r"putic[ao]s?", r"putit[ao]s?", r"putamadre", r"malparid[ao]s?", r"gonorreas?",
    r"care\s?(chimba|verga|monda|culo)s?", r"vergas?", r"vergazos?", r"mondas?", r"pirob[ao]s?",
    r"maric[ao]s?", r"maricon(es)?", r"marik[ao]s?", r"(g|h|w)u?e(v|b)on(a|es|as)?", r"weon(a|es)?",
    r"pendej[ao]s?", r"cabron(a|es|as)?", r"cono\s?de\s?(tu|su)\s?madre", r"mierdas?", r"mierder[ao]",
    r"perras?", r"zorras?", r"idiotas?", r"imbeciles?", r"estupid[ao]s?", r"tarad[ao]s?",
    r"retrasad[ao]s?", r"mamaguev[ao]s?", r"mamahuev[ao]s?", r"chupa\s?(me\s?)?(la|lo|pija|verga|monda)",
    r"chupame(la|lo)?", r"culo", r"culos", r"culi(ar|ear|ado|ada)", r"cule(ar|o)", r"culicagad[ao]s?",
    r"chingad[ao]s?", r"chingar", r"joder", r"jodete", r"lambon(a|es)?", r"lameculos",
    # sexual content
    r"sexo", r"sexual(es)?", r"porno", r"pornografia", r"tetas?", r"pene", r"penes", r"vaginas?",
    r"follar", r"mamada", r"orgasmos?", r"masturba\w*", r"desnud[ao]s?", r"pajero",
    r"cachond[ao]", r"verguer[ao]",
    # English
    r"fuck\w*", r"motherfucker", r"shit", r"bitch(es)?", r"asshole", r"dick", r"pussy", r"porn", r"nude",
]

# Some speech recognisers censor profanity themselves: "h*********", "f***".
CENSORED = re.compile(r"\b[a-z]\*{2,}|\*{3,}")

LEET = str.maketrans({"4": "a", "@": "a", "3": "e", "1": "i", "!": "i", "0": "o", "$": "s", "5": "s", "7": "t"})

def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c)).replace("ñ", "n")
    text = text.translate(LEET)
    text = re.sub(r"(.)\1{2,}", r"\1", text)  # "putaaaa" -> "puta"
    text = re.sub(r"(?<=\b\w)[.\-_](?=\w\b)", "", text)  # "p.u.t.a" -> "puta"
    return re.sub(r"[^a-z0-9*\s]", " ", text)

def _load_config() -> tuple[list[str], set[str]]:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], set()
    block = [re.escape(normalize(w).strip()) for w in data.get("bloquear", []) if str(w).strip()]
    allow = {normalize(w).strip() for w in data.get("permitir", []) if str(w).strip()}
    return block, allow

_cache: dict = {"mtime": None, "regex": None, "allow": set()}

def _matcher() -> tuple[re.Pattern, set[str]]:
    """Compiled patterns; the config file is re-read when it changes (no restart needed)."""
    try:
        mtime = CONFIG_PATH.stat().st_mtime
    except OSError:
        mtime = None
    if _cache["regex"] is None or _cache["mtime"] != mtime:
        extra, allow = _load_config()
        body = "|".join(f"(?:{p})" for p in [*PATTERNS, *extra])
        _cache.update(mtime=mtime, regex=re.compile(rf"\b(?:{body})\b"), allow=allow)
    return _cache["regex"], _cache["allow"]

def is_offensive(text: str | None) -> bool:
    if not text:
        return False
    if CENSORED.search(text.lower()):
        return True
    plain = normalize(text)
    regex, allow = _matcher()
    for match in regex.finditer(plain):
        if match.group(0).strip() not in allow:
            return True
    return False

def closing_message(company: str) -> str:
    return ("Prefiero que mantengamos una conversación respetuosa, así que voy a terminar aquí. "
            f"Si necesitas algo de {company}, puedes volver cuando quieras.")
