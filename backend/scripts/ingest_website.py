"""Downloads the public content of the company website into knowledge_chunks.

Usage:
    python -m backend.scripts.ingest_website

Only curated sources are ingested (theme demo pages such as "Home 2" or
"Portfolio 3" are ignored). A JSON snapshot is written to data/knowledge/ so
every answer can be traced back to what the site said at ingestion time.
"""
import io
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader
from sqlalchemy import delete, insert

from backend.app.core.config import settings
from backend.app.core.db import init_db, knowledge_chunks, make_engine

SNAPSHOT_PATH = Path("data/knowledge/website_snapshot.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (OskiIngest/1.0)"}
MAX_CHUNK_CHARS = 700

# Curated pages rendered as HTML. Services are discovered from the homepage.
HTML_PAGES = [
    ("", "Inicio", "empresa"),
    ("?page_id=11668", "Nosotros", "empresa"),
    ("?page_id=9592", "Contacto", "contacto"),
]
# Pages read through the WordPress REST API (clean content, no menus).
REST_PAGES = [
    (3, "politica"),
    (18917, "politica"),
    (18932, "politica"),
]

def fetch(client: httpx.Client, url: str) -> httpx.Response:
    response = client.get(url, headers=HEADERS, follow_redirects=True, timeout=60)
    response.raise_for_status()
    return response

JUNK_LINE = re.compile(
    r"©|all rights reserved|^enviar$|^cart$|items\)|your cart is empty|browse shop|^search$"
    r"|^[.\s]*(tecnolog[ií]a|innovaci[oó]n|seguridad|soluciones estrat[eé]gicas|cont[aá]ct[ae]nos)[.\s]*$",
    re.IGNORECASE,
)

def clean_lines(text: str) -> list[str]:
    lines = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if len(line) < 3 or line in {"//", "→"} or JUNK_LINE.search(line):
            continue
        if lines and lines[-1] == line:  # repeated headings
            continue
        lines.append(line)
    return lines

def html_to_lines(html: str) -> tuple[str | None, list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "form", "nav"]):
        tag.decompose()
    heading = soup.find(["h1", "h2"])
    title = heading.get_text(" ", strip=True) if heading else None
    body = soup.body or soup
    return title, clean_lines(body.get_text("\n", strip=True))

def is_heading(line: str) -> bool:
    return len(line) <= 40 and not line.endswith(".")

def chunk(lines: list[str]) -> list[str]:
    chunks, current = [], []
    for line in lines:
        if current and len("\n".join(current)) + len(line) + 1 > MAX_CHUNK_CHARS:
            # Keep a trailing heading ("Visión") together with its paragraph.
            carry = [current.pop()] if len(current) > 1 and is_heading(current[-1]) else []
            chunks.append("\n".join(current))
            current = carry
        current.append(line)
    if current:
        chunks.append("\n".join(current))
    return chunks

def remove_boilerplate(pages: list[dict]) -> None:
    """Drops lines (menus, footer) that repeat across most HTML pages."""
    counts = Counter(line for p in pages for line in set(p["lines"]))
    threshold = max(2, int(len(pages) * 0.5))
    for page in pages:
        page["lines"] = [l for l in page["lines"] if counts[l] < threshold]

def collect_html(client: httpx.Client, base: str) -> list[dict]:
    home = fetch(client, base).text
    service_slugs = sorted(set(re.findall(r"\?service=([a-z0-9\-]+)", home)))
    targets = [(path, title, kind) for path, title, kind in HTML_PAGES]
    targets += [(f"?service={slug}", None, "servicio") for slug in service_slugs]

    pages, contact_html = [], home
    for path, title, kind in targets:
        url = urljoin(base, path)
        html = home if path == "" else fetch(client, url).text
        if kind == "contacto":
            contact_html = html + home
        page_title, lines = html_to_lines(html)
        pages.append({"url": url, "title": title or page_title or path, "kind": kind, "lines": lines})
        print(f"  html  {kind:9} {url}")
    contact = contact_details(contact_html)
    remove_boilerplate(pages)
    if contact:
        pages.append(contact)
    return pages

def contact_details(html: str) -> dict | None:
    """Phone, email, address and social links published in the site footer."""
    soup = BeautifulSoup(html, "html.parser")
    lines = clean_lines(soup.get_text("\n", strip=True))
    labels = {"Mesa de ayuda": "Mesa de ayuda", "Dirección": "Dirección", "Email": "Correo electrónico"}
    found = {}
    for i, line in enumerate(lines[:-1]):
        for label, name in labels.items():
            if line.lower() == label.lower() and name not in found:
                found[name] = lines[i + 1]
    whatsapp = re.search(r"https://wa\.me/(\d+)", html)
    if whatsapp:
        found["WhatsApp"] = whatsapp.group(1)
    if not found:
        return None
    details = [f"Datos de contacto de {settings.company_name}:"]
    details += [f"{name}: {value}." for name, value in found.items()]
    return {"url": urljoin(settings.website_url, "?page_id=9592"), "title": "Datos de contacto",
            "kind": "contacto", "lines": [" ".join(details)]}

def collect_rest(client: httpx.Client, base: str) -> list[dict]:
    api = urljoin(base, "index.php?rest_route=/wp/v2/")
    items = [(f"{api}pages/{page_id}", kind) for page_id, kind in REST_PAGES]
    posts = fetch(client, f"{api}posts&per_page=100&_fields=id").json()
    items += [(f"{api}posts/{p['id']}", "articulo") for p in posts]

    pages = []
    for url, kind in items:
        data = fetch(client, url).json()
        title = BeautifulSoup(data["title"]["rendered"], "html.parser").get_text(" ", strip=True)
        _, lines = html_to_lines(data["content"]["rendered"])
        pages.append({"url": data["link"], "title": title, "kind": kind, "lines": lines})
        print(f"  rest  {kind:9} {data['link']}")
    return pages

def collect_pdfs(client: httpx.Client, base: str) -> list[dict]:
    home = fetch(client, base).text
    pdf_urls = sorted(set(re.findall(r"https://[^\"']+?\.pdf", home)))
    pages = []
    for url in pdf_urls:
        reader = PdfReader(io.BytesIO(fetch(client, url).content))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        title = Path(url).stem.replace("-", " ")
        pages.append({"url": url, "title": title, "kind": "politica", "lines": clean_lines(text)})
        print(f"  pdf   politica  {url}")
    return pages

def solutions_overview(pages: list[dict]) -> dict | None:
    """Index of the services found on the site (built only from crawled titles)."""
    services = [p for p in pages if p["kind"] == "servicio"]
    if not services:
        return None
    names = [p["title"] for p in services]
    listing = ", ".join(names[:-1]) + f" y {names[-1]}" if len(names) > 1 else names[0]
    lines = [f"Los servicios y soluciones de {settings.company_name} son: {listing}."]
    return {"url": settings.website_url, "title": f"Soluciones de {settings.company_name}", "kind": "servicio", "lines": lines}

def ingest(engine=None) -> int:
    base = settings.website_url
    print(f"Ingesting {base}")
    with httpx.Client() as client:
        pages = collect_html(client, base) + collect_rest(client, base) + collect_pdfs(client, base)

    overview = solutions_overview(pages)
    if overview:
        pages.append(overview)

    rows = [
        {"source_url": p["url"], "title": p["title"], "kind": p["kind"], "content": c}
        for p in pages
        for c in chunk(p["lines"])
    ]
    if not rows:
        raise SystemExit("No content found; aborting without touching the knowledge base.")

    engine = engine or make_engine()
    init_db(engine, seed=False)
    with engine.begin() as conn:
        conn.execute(delete(knowledge_chunks))
        conn.execute(insert(knowledge_chunks), rows)

    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(
        json.dumps(
            {"source": base, "fetched_at": datetime.now(timezone.utc).isoformat(), "chunks": rows},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Stored {len(rows)} chunks from {len(pages)} sources. Snapshot: {SNAPSHOT_PATH}")
    return len(rows)

def load_snapshot(engine=None) -> int:
    """Loads the saved snapshot of the site into the knowledge base (no network)."""
    rows = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))["chunks"]
    engine = engine or make_engine()
    init_db(engine, seed=False)
    with engine.begin() as conn:
        conn.execute(delete(knowledge_chunks))
        conn.execute(insert(knowledge_chunks), rows)
    return len(rows)

def main():
    ingest()

if __name__ == "__main__":
    main()
