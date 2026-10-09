# Publicar Osky gratis

Arquitectura de costo cero:

| Pieza | Servicio | Plan |
|---|---|---|
| Página (lo que ve la gente) | Cloudflare Pages | Gratis, uso comercial, HTTPS |
| Backend (búsqueda, WhatsApp, datos) | Render | Gratis (512 MB; se duerme tras 15 min sin uso) |
| Escuchar (voz → texto) | Groq · Whisper large-v3 turbo | Gratis, sin tarjeta (≈2.000 turnos/día) |
| Redactar respuestas naturales | Groq · Llama 3.3 70B | Gratis, con límites diarios |
| Hablar (texto → voz) | Azure Speech F0 (opcional) | Gratis 500.000 caracteres/mes |
| Registro de conversaciones | Neon (PostgreSQL) | Gratis, sin tarjeta (0,5 GB) |
| Mantenerlo despierto | cron-job.org | Gratis |

> Sin Azure, Osky usa una voz neuronal gratuita alternativa (la misma voz de Gonzalo, pero sin garantía de servicio).

---

## 1. Subir el proyecto a GitHub

1. Crea una cuenta en <https://github.com> y un repositorio **privado** llamado `oski` (sin README).
2. En una terminal, dentro de la carpeta del proyecto:

```bash
git init
git add .
git commit -m "Osky: asistente de voz de CeluWeb"
git branch -M main
git remote add origin https://github.com/TU-USUARIO/oski.git
git push -u origin main
```

El archivo `.env` (con tus claves locales) **no** se sube: está excluido en `.gitignore`.

## 2. Clave de Groq (gratis, sin tarjeta)

1. Entra a <https://console.groq.com> con tu correo.
2. **API Keys → Create API Key** → copia la clave (empieza por `gsk_`). Guárdala; no se vuelve a mostrar.

## 3. (Opcional) Voz oficial de Azure gratis

1. <https://portal.azure.com> → **Crear un recurso** → busca **Speech** → Crear.
2. Plan de precios **Free F0**, región **East US**.
3. En el recurso: **Claves y punto de conexión** → copia **Clave 1** y la **región** (`eastus`).

## 3b. Base de datos para el registro de conversaciones (Neon, gratis)

El disco del plan gratis de Render se borra en cada publicación, así que el registro de conversaciones
(nombre, hora, preguntas) se guarda en una base PostgreSQL gratuita:

1. <https://neon.tech> → crea una cuenta y un proyecto (región **US East**).
2. **Connection string** → copia la cadena. Se ve así: `postgresql://usuario:clave@ep-xxx.us-east-2.aws.neon.tech/neondb?sslmode=require`
3. Cámbiale el inicio `postgresql://` por **`postgresql+psycopg://`**. Ese es tu `DATABASE_URL`.

Las tablas se crean solas al arrancar.

## 4. Backend en Render

1. Entra a <https://render.com> con tu cuenta de GitHub.
2. **New → Blueprint** → elige el repositorio `oski`. Render lee `render.yaml` y crea el servicio `oski-api`.
3. Te pedirá:
   - `GROQ_API_KEY`: la clave del paso 2.
   - `AZURE_SPEECH_KEY`: la del paso 3 (o déjala vacía).
   - `DATABASE_URL`: la del paso 3b.
   - `CORS_ORIGINS`: déjala vacía por ahora (se completa en el paso 6).
4. **Apply**. Cuando termine verás una dirección como `https://oski-api.onrender.com`.
5. Prueba abriendo `https://oski-api.onrender.com/health` → debe decir `"status":"ok"`.

## 5. Página en Cloudflare Pages

1. <https://dash.cloudflare.com> → **Workers & Pages → Create → Pages → Connect to Git** → repositorio `oski`.
2. Configuración de compilación:
   - **Framework preset:** Vite (o None)
   - **Root directory:** `frontend`
   - **Build command:** `npm run build`
   - **Build output directory:** `dist`
   - **Variable de entorno:** `VITE_API_URL` = `https://oski-api.onrender.com` (la del paso 4)
3. **Save and Deploy**. Quedará en algo como `https://oski.pages.dev`.

## 6. Conectar página y backend

En Render → `oski-api` → **Environment** → `CORS_ORIGINS` = `https://oski.pages.dev`
(si luego usas dominio propio, agrégalo separado por coma: `https://oski.pages.dev,https://oski.celuweb.com`).
Guarda: Render se reinicia solo.

Abre `https://oski.pages.dev` → ¡Osky está en línea! (`?modo=persona` abre directo el astronauta).

## 7. Que no se duerma (gratis)

El plan gratis de Render se duerme tras 15 min sin visitas y tarda ~1 minuto en despertar.
En <https://cron-job.org> crea un trabajo: URL `https://oski-api.onrender.com/health`, **cada 10 minutos**.
Las 750 horas gratis al mes alcanzan para tenerlo encendido 24/7.

## 8. (Opcional) Dominio propio: oski.celuweb.com

Cloudflare Pages → tu proyecto → **Custom domains → Set up a domain** → `oski.celuweb.com` y sigue las instrucciones
(crear un registro CNAME en el DNS de celuweb.com). Luego agrégalo a `CORS_ORIGINS` (paso 6).

## 9. Botón "Habla con Osky" en celuweb.com

Copia `docs/widget-wordpress.html`, cambia `OSKI_URL` por tu dirección y pégalo en el pie de página de WordPress
(plugin "Insert Headers and Footers" o bloque HTML personalizado). En celulares se abre a pantalla completa.

---

## Darle más contexto a Osky

Todo se edita en GitHub (botón ✏️ en cada archivo) y Render vuelve a publicar solo en ~2 minutos:

- **Documentos** → carpeta `conocimiento/` (PDF, Word, TXT, MD): botón **Add file → Upload files**.
- **Datos oficiales** → `config/company_facts.json`.
- **Comerciales y WhatsApp** → `config/sales_contacts.json`.
- **Contenido del sitio** → se guarda en `data/knowledge/website_snapshot.json`. Para actualizarlo cuando cambie
  celuweb.com, en tu PC: `python -m backend.scripts.ingest_website` y sube el archivo actualizado a GitHub.
  (También existe `POST /api/knowledge/refresh` con el encabezado `X-Admin-Token`, pero en el plan gratis ese
  cambio se pierde al reiniciar; el archivo en GitHub es lo permanente.)

## Registro de conversaciones

Osky pregunta el nombre al empezar y guarda cada conversación: nombre, fecha y hora, cada pregunta y respuesta,
y a qué comercial se envió por WhatsApp.

- Ver el registro: abre `https://oski.pages.dev/?admin=1` (tu dirección + `?admin=1`).
- Te pedirá el `ADMIN_TOKEN`: en Render → `oski-api` → **Environment** → `ADMIN_TOKEN` → ver valor.
- **⬇ Exportar CSV** descarga todo para Excel (horas de Colombia).
- Los visitantes ven un aviso con enlace a la política de datos de CeluWeb.

## Límites y cuándo pagar

- Gratis significa **sin garantía de servicio**: ideal para piloto y demostraciones.
- Si los límites de Groq se agotan en un día, Osky sigue respondiendo con el texto literal (sin redacción natural)
  y la escucha pasa al reconocimiento del navegador.
- Si el uso crece: Render Starter (~USD 7/mes) quita el "sueño" y da más capacidad.
- Privacidad: revisa los términos de Groq y Azure frente a la política de datos de CeluWeb (Ley 1581) antes de
  usarlo con datos de clientes. Osky no pide datos personales.
