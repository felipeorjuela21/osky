# Osky — Agente de voz de CeluWeb

Osky es el asistente de voz de CeluWeb. Responde **solo con información oficial de la empresa**:
el contenido público de https://www.celuweb.com/ y, más adelante, los datos empresariales autorizados.
No es un chatbot general y no inventa datos.

## Cómo responde

```
celuweb.com ──ingesta──> knowledge_chunks (BD) ──búsqueda BM25──> extracto literal + fuente
                                                                        │
Micrófono ─STT─> pregunta ─> /api/ask ──────────────────────────────────┘ ─> respuesta ─TTS─> voz
```

- **Fuente de verdad**: lo que dice el sitio en el momento de la ingesta. Cada respuesta es un extracto literal y trae su URL.
- **Si no lo encuentra, lo dice**: "No encontré esa información en las fuentes oficiales de CeluWeb".
- **Voz**: voz neuronal generada en el servidor y reconocimiento de voz con Whisper en el servidor (ver abajo).
- **Datos estructurados (ventas/clientes)**: el motor Query AST + parser de español sigue disponible, pero las tablas de ejemplo están **desactivadas** (`ENABLE_DEMO_DATA=false`) para que Osky no responda con cifras falsas.

> **Publicarlo gratis** (Cloudflare Pages + Render + Groq + Azure F0): ver [docs/DESPLIEGUE.md](docs/DESPLIEGUE.md).
> **Darle más contexto:** documentos en `conocimiento/`, datos en `config/company_facts.json`,
> comerciales en `config/sales_contacts.json`.

## Modos

- **💬 Chat**: conversación escrita con micrófono opcional (pulsar para hablar) y respuestas con su fuente.
- **🧑‍🚀 Persona**: Osky es el astronauta de celuweb.com en el espacio y conversa por voz, manos libres. Llega
  flotando y saluda con la mano, te mira (sigue el cursor), se inclina para escucharte, asiente cuando terminas,
  ladea la cabeza al pensar y gesticula al hablar: cabeza, manos y la luz del visor siguen el volumen real de su
  voz. Se encoge de hombros si no sabe algo y, al decir "adiós", se va flotando. Respuestas cortas para voz
  ("¿Te cuento más?"), subtítulos sincronizados y botones de WhatsApp. Se interrumpe tocándolo o con la barra
  espaciadora. Abre directo con `http://localhost:5174/?modo=persona`.

### Voz
La voz es **neuronal y la genera el backend** (`/api/tts`, voz por defecto `es-CO-GonzaloNeural`), con los
tiempos de cada palabra para mover los labios. Osky usa solo voces masculinas. Se cambia con el botón **🎙️ Voz** o en `.env`
(`TTS_VOICE`, `TTS_RATE`). Si el servicio no responde, se usa la voz del navegador.

> Prototipo: `TTS_PROVIDER=edge` usa el servicio de lectura en voz alta de Microsoft Edge (paquete `edge-tts`),
> gratuito pero no oficial. Para producción usar **Azure Speech** (mismas voces, con clave y SLA).

### Asesores comerciales por WhatsApp
Cuando alguien pide un asesor, una cotización o precios (o después de explicar una solución), Osky muestra un
botón de WhatsApp con el mensaje ya escrito ("Hola, vengo de Osky… Me interesa TMS"). Los asesores se editan en
**`config/sales_contacts.json`** (sin reiniciar):

```json
{ "name": "Ana Pérez", "phone": "573001234567", "area": "Logística", "solutions": ["TMS", "Mapas"], "active": true }
```

`phone` va con indicativo y sin `+`. Con `solutions` vacío el asesor atiende todo; si varios asesores atienden lo
mismo, Osky reparte las conversaciones entre ellos. Soluciones válidas: TMS, Pricing, Chat Bot, B2B, Field Service,
Televenta, Supervisores, Link de pagos, Mapas, Mercadeo, Fuerza de Ventas, Entregas.

### Datos oficiales que no están en la web
**`config/company_facts.json`** guarda datos aprobados por CeluWeb (por ejemplo, "somos más de 140 personas").
Osky los usa como fuente oficial y los cita como "dato oficial de CeluWeb".

### Reconocimiento de voz (micrófono)
La voz del usuario se graba en el navegador (detecta cuándo empiezas y terminas de hablar) y se transcribe en
**nuestro servidor con Whisper** (`faster-whisper`, modelo `base`, CPU, sin internet ni claves): ~1–2 s por frase.
No depende del servicio de voz de Google en Chrome. Incluye correcciones de términos de CeluWeb (TMS, Pricing…)
en `backend/app/services/stt.py`. En **🎙️ Voz** se elige el micrófono y hay un medidor para probarlo.
La primera vez descarga el modelo (~140 MB) en `data/models/`; `STT_MODEL=small` es más preciso pero más lento
y necesita más RAM. `STT_PROVIDER=browser` vuelve al reconocimiento del navegador.

## Requisitos

- Python 3.11+
- Node 20+
- Chrome o Edge (para hablarle a Osky)
- Docker **no** es necesario: por defecto usa SQLite (`data/enterprise_agent.db`).

## Arranque rápido (Windows)

```powershell
powershell -ExecutionPolicy Bypass -File .\start-oski.ps1
```

Instala lo necesario la primera vez, abre el backend (:8000) y el frontend (:5174), y abre el navegador.
La primera vez que arranca con la base vacía, el backend descarga celuweb.com en segundo plano (~30 s).

## Arranque manual

```bash
cp .env.example .env
python -m venv .venv
.venv\Scripts\activate
pip install -r backend/requirements-local.txt
python -m backend.scripts.ingest_website        # descarga celuweb.com a la base
uvicorn backend.app.main:app --reload --port 8000

cd frontend
npm install
npm run dev                                      # http://localhost:5174
```

## Abrir Osky en el teléfono (misma red Wi-Fi)

```bash
cd frontend
npm run dev:lan        # https://<IP-del-PC>:5175  (ver "Network" en la consola)
```

Usa HTTPS con un certificado autofirmado porque los navegadores móviles solo permiten el micrófono en páginas
seguras: la primera vez el teléfono muestra un aviso de seguridad → "Avanzado / Más información" → "Continuar".
El backend sigue privado en el PC; el teléfono solo habla con este servidor. Ambos equipos deben estar en la
misma red (algunas redes corporativas o de invitados aíslan los dispositivos y no lo permiten).

## Logo de Osky

El avatar es el astronauta de celuweb.com (`frontend/public/oski.png`) y el logo CW está en `frontend/public/celuweb-logo.png`. Para cambiarlo, reemplaza esos archivos (PNG cuadrado con fondo transparente).
Si falta `oski.png`, se muestra el marcador `frontend/public/oski.svg`.

### Astronauta articulado

El astronauta está separado en capas (cuerpo, brazos, mano, casco y piernas) en `frontend/public/oski-rig/`
y se anima desde sus articulaciones (`frontend/src/components/rig.css`); la luz del visor reacciona a su voz
y a la tuya.
Para regenerar las capas desde la imagen original:

```bash
pip install pillow numpy
python frontend/scripts/build_rig.py ruta/a/Astro-1.png
```

## Actualizar la información del sitio

```bash
python -m backend.scripts.ingest_website
# o, con el backend corriendo:
curl -X POST http://localhost:8000/api/knowledge/refresh
```

Se ingieren: Inicio, Nosotros, Contacto, las soluciones (`?service=...`), los artículos del blog,
las páginas de políticas y los PDF de políticas enlazados. Las páginas de demo de la plantilla
(Home 2…8, Portfolio, Team, Shop) se ignoran. Queda una copia en `data/knowledge/website_snapshot.json`
para auditar qué decía el sitio.

## API

| Método | Ruta | Uso |
|---|---|---|
| GET | `/health` | Estado |
| GET | `/api/agent` | Nombre, empresa y saludo de Osky |
| POST | `/api/ask` | `{"question": "..."}` → respuesta + fuentes |
| GET | `/api/knowledge` | Fragmentos cargados por tipo y fecha de ingesta |
| POST | `/api/knowledge/refresh` | Re-descarga el sitio |
| GET | `/api/logs` | Últimas preguntas y respuestas (auditoría) |
| POST | `/api/query` | Query AST validado (datos estructurados) |
| GET | `/api/dictionary` | Diccionario de datos |

Documentación interactiva: http://localhost:8000/docs

## Tests

```bash
python -m pytest backend
```

## Principios

1. Las fuentes oficiales de la empresa son la fuente de verdad.
2. Si no existe el dato, el agente debe decirlo.
3. No inventar cifras, nombres, fechas ni métricas.
4. Separar interpretación de consulta y ejecución.
5. No ejecutar SQL arbitrario generado por un usuario.
6. Toda fuente debe tener esquema y permisos definidos.
7. Las respuestas deben ser trazables (cada respuesta trae su fuente; todo queda en `query_log`).

## PostgreSQL (opcional)

```bash
docker compose up -d db
# en .env:
DATABASE_URL=postgresql+psycopg://agent:agent@localhost:5432/enterprise_agent
```
