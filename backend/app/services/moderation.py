"""Forbidden language and topics, in Spanish and English: they end the conversation.

Runs before anything else (no LLM call, no search), on every text the visitor sends:
the name, each question and the follow-up turns. Words are matched as whole words
after normalising accents, leetspeak ("h1jueput4") and stretched letters
("putaaaa"), so "computadora" or "disputa" never match.

Categories: insults, sexual content and prostitution, minors, drugs, violence and
weapons, hate, crimes, and self-harm (which gets a help line instead of a cold goodbye).
The language model is a second barrier for phrasings that no list catches (llm.py).

Words that are normal in CeluWeb's business are deliberately NOT blocked: "drogas"
alone (droguerías are pharmacies), "prepago" (phone plans), "violación de datos".

Extra words can be added without touching code in config/lenguaje_bloqueado.json
("bloquear"), and false positives can be allowed there too ("permitir").
"""
import json
import re
import unicodedata
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "lenguaje_bloqueado.json"

# Regex stems on normalised text (lowercase, no accents, ñ -> n). Each one is matched
# as a whole word. Order matters: self-harm is checked before violence ("matarme").
CATEGORIES: dict[str, list[str]] = {
    "autolesion": [
        r"suicid\w*", r"quitarme la vida", r"matarme", r"me quiero morir", r"no quiero vivir( mas)?",
        r"cortarme (las venas|los brazos)", r"autolesion\w*", r"hacerme dano",
        r"kill myself", r"end my life", r"want to die", r"self harm\w*",
    ],
    "menores": [
        r"menor(es)? de edad", r"menorcit[ao]s?", r"pedofil\w*", r"pederast\w*", r"pornografia infantil",
        r"abuso (sexual )?infantil", r"explotacion (sexual )?infantil", r"lolis?",
        r"underage", r"child (porn\w*|abuse|sex\w*)", r"p(a)?edophil\w*", r"jailbait", r"preteens?",
    ],
    "sexual": [
        r"prostitu\w*", r"prostibulos?", r"burdel(es)?", r"proxenet\w*", r"escorts?", r"scorts?",
        r"damas? de compania", r"servicios? sexual(es)?", r"sexo", r"sexual(es)?", r"sexy", r"porno\w*",
        r"pornografia", r"tetas?", r"pene", r"penes", r"vaginas?", r"follar", r"mamada",
        r"orgasmos?", r"masturba\w*", r"desnud[ao]s?", r"pajero", r"cachond[ao]", r"verguer[ao]",
        r"onlyfans", r"fotos? intimas?", r"contenido intimo", r"eroti\w*", r"violacion sexual",
        r"violar a", r"abuso sexual", r"acoso sexual", r"trata de (personas|blancas|mujeres)",
        r"sex", r"porn\w*", r"nudes?", r"naked", r"hookers?", r"brothels?", r"pimps?", r"blowjob",
        r"handjob", r"boobs?", r"tits", r"penis", r"rape[ds]?", r"rapists?", r"molest\w*",
    ],
    "drogas": [
        r"narcotrafic\w*", r"narcos?", r"cocaina", r"marihuana", r"marijuana", r"mariguana", r"cannabis",
        r"heroina", r"metanfetamina", r"fentanilo", r"extasis", r"lsd", r"basuco", r"bazuco", r"tusi",
        r"drogas? ilegal(es)?", r"(vender|comprar|traficar|conseguir) (droga|drogas|coca|perico)",
        r"cocaine", r"heroin", r"meth", r"fentanyl", r"weed", r"ecstasy", r"mdma", r"crack",
        r"illegal drugs?", r"(sell|buy) drugs",
    ],
    "violencia": [
        r"(hacer|fabricar|poner|armar) (una )?bomba", r"explosivos?", r"terroris\w*", r"atentados?",
        r"matar a", r"matarte", r"matarlo", r"matarla", r"te voy a matar", r"asesin\w*", r"sicari\w*",
        r"secuestr\w*", r"extorsi\w*", r"armas? de fuego", r"(comprar|vender|conseguir) armas?",
        r"pistolas?", r"fusil(es)?", r"granadas?", r"masacres?", r"tortur\w*", r"tiroteos?",
        r"kill (you|him|her|them|people|everyone)", r"murder\w*", r"bombs?", r"explosives?", r"guns?",
        r"weapons?", r"shooting", r"kidnap\w*", r"massacre",
    ],
    "odio": [
        r"nazi\w*", r"hitler", r"heil", r"white power", r"supremacista\w*", r"sudacas?",
        r"nigg(er|a)s?", r"faggots?", r"fags?", r"retard(ed|s)?", r"chinks?", r"spics?", r"kikes?", r"trann(y|ies)",
    ],
    "delitos": [
        r"hackear\w*", r"hackeo", r"robar (contrasenas?|claves?|cuentas?|datos|tarjetas?|dinero)",
        r"phishing", r"lavado de (dinero|activos)", r"lavar (dinero|plata)", r"trafico de (personas|organos|armas)",
        r"falsificar\w*", r"documentos? fals[oa]s?", r"estafar\w*",
        r"money launder\w*", r"launder(ing)? money", r"steal (passwords?|accounts?|credit cards?|money)",
        r"human trafficking", r"counterfeit\w*", r"scam people",
    ],
    "lenguaje": [
        # Colombian / Latin American insults
        r"(h|j)?ij?[oue]e?\s?(de\s?(su|tu)?\s?)?put[ao]s?", r"hpt[ao]s?", r"jueput[ao]s?", r"ptm",
        r"put[ao]s?", r"putic[ao]s?", r"putit[ao]s?", r"putamadre", r"malparid[ao]s?", r"malnacid[ao]s?",
        r"gonorreas?", r"care\s?(chimba|verga|monda|culo|picha)s?", r"vergas?", r"vergazos?", r"mondas?",
        r"pirob[ao]s?", r"maric[ao]s?", r"maricon(es)?", r"marik[ao]s?", r"(g|h|w)u?e(v|b)on(a|es|as)?",
        r"weon(a|es)?", r"pendej[ao]s?", r"cabron(a|es|as)?", r"cono\s?de\s?(tu|su)\s?madre", r"mierdas?",
        r"mierder[ao]", r"comemierdas?", r"perras?", r"zorras?", r"zungas?", r"pichurrias?", r"idiotas?",
        r"imbeciles?", r"estupid[ao]s?", r"tarad[ao]s?", r"retrasad[ao]s?", r"mamaguev[ao]s?",
        r"mamahuev[ao]s?", r"chupa\s?(me\s?)?(la|lo|pija|verga|monda)", r"chupame(la|lo)?", r"culo", r"culos",
        r"culi(ar|ear|ado|ada)", r"cule(ar|o)", r"culicagad[ao]s?", r"chingad[ao]s?", r"chingar", r"joder",
        r"jodete", r"lambon(a|es)?", r"lameculos", r"lambeculos",
        # English
        r"fuck\w*", r"motherfuck\w*", r"shit\w*", r"bitch(es|y)?", r"assholes?", r"dicks?", r"pussy",
        r"cunts?", r"whores?", r"sluts?", r"bastards?", r"dumbass", r"jackass", r"wankers?", r"twats?",
        r"cocks?", r"suck my", r"screw you", r"stfu", r"idiots?", r"stupid", r"morons?",
    ],
}

# Some speech recognisers censor profanity themselves: "h*********", "f***".
CENSORED = re.compile(r"\b[a-z]\*{2,}|\*{3,}")

LEET = str.maketrans({"4": "a", "@": "a", "3": "e", "1": "i", "!": "i", "0": "o", "$": "s", "5": "s", "7": "t"})

def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c)).replace("ñ", "n")
    text = text.translate(LEET)
    text = re.sub(r"(.)\1{2,}", r"\1", text)  # "putaaaa" -> "puta"
    text = re.sub(r"(?<=\b\w)[.\-_](?=\w\b)", "", text)  # "p.u.t.a" -> "puta"
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text)

def _load_config() -> tuple[list[str], set[str]]:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], set()
    block = [re.escape(normalize(w).strip()) for w in data.get("bloquear", []) if str(w).strip()]
    allow = {normalize(w).strip() for w in data.get("permitir", []) if str(w).strip()}
    return block, allow

_cache: dict = {"mtime": None, "regexes": None, "allow": set()}

def _matchers() -> tuple[list[tuple[str, re.Pattern]], set[str]]:
    """Compiled patterns per category; the config file is re-read when it changes (no restart)."""
    try:
        mtime = CONFIG_PATH.stat().st_mtime
    except OSError:
        mtime = None
    if _cache["regexes"] is None or _cache["mtime"] != mtime:
        extra, allow = _load_config()
        groups = {**CATEGORIES, "bloqueado": extra} if extra else CATEGORIES
        regexes = [(name, re.compile(rf"\b(?:{'|'.join(f'(?:{p})' for p in patterns)})\b"))
                   for name, patterns in groups.items()]
        _cache.update(mtime=mtime, regexes=regexes, allow=allow)
    return _cache["regexes"], _cache["allow"]

def classify(text: str | None) -> str | None:
    """The forbidden category the text falls in ("lenguaje", "sexual", "menores"...), or None."""
    if not text:
        return None
    if CENSORED.search(text.lower()):
        return "lenguaje"
    plain = normalize(text)
    regexes, allow = _matchers()
    for name, regex in regexes:
        for match in regex.finditer(plain):
            if match.group(0).strip() not in allow:
                return name
    return None

def is_offensive(text: str | None) -> bool:
    return classify(text) is not None

def end_reason(category: str) -> str:
    """What the admin log shows as the reason the conversation was closed."""
    return "lenguaje_inapropiado" if category in ("lenguaje", "bloqueado") else f"tema_prohibido:{category}"

def closing_message(company: str, category: str = "lenguaje") -> str:
    if category == "autolesion":
        return ("Siento mucho que estés pasando por algo así. No soy la ayuda adecuada para esto, pero no estás "
                "solo: en Colombia puedes llamar gratis a la línea 192, opción 4, o al 123 si es una emergencia.")
    if category in ("lenguaje", "bloqueado"):
        return ("Prefiero que mantengamos una conversación respetuosa, así que voy a terminar aquí. "
                f"Si necesitas algo de {company}, puedes volver cuando quieras.")
    return ("Ese es un tema del que no puedo hablar, así que voy a terminar aquí la conversación. "
            f"Si necesitas algo de {company}, puedes volver cuando quieras.")
