# Próximos pasos

## Hecho
- Backend FastAPI con SQLite por defecto (PostgreSQL opcional).
- Ingesta de celuweb.com (páginas, soluciones, blog, políticas y PDF) a `knowledge_chunks`, con snapshot JSON.
- Búsqueda BM25 en español con sinónimos; responde con extracto literal + fuente, o dice que no lo encontró.
- Query AST validado contra el Data Dictionary + parser de español para datos estructurados (desactivado hasta tener datos reales).
- Registro de cada pregunta/respuesta en `query_log`.
- Frontend React + TS "Osky": micrófono (STT) y voz (TTS) del navegador, estados idle/listening/thinking/speaking, interrupción (barge-in).

## Pendiente
1. **Logo de Osky** → `frontend/public/oski.png`.
2. **Revisar inconsistencias del sitio**: el pie de página dice "Carrera 14 N 15 Edificio Icono" y mesa de ayuda +57 320 889 9518;
   la política de privacidad dice "Carrera 14 No. 35-18" y +57 320 671 8302. Osky repite lo que diga cada fuente.
3. **Respuestas más naturales (opcional)**: usar un LLM solo para redactar a partir de los fragmentos recuperados,
   con instrucción de no añadir datos y verificación de que cada cifra aparece en la fuente.
4. **Datos reales**: cargar el primer Excel (`python -m backend.scripts.import_csv archivo.xlsx tabla`),
   declararlo en `backend/app/core/data_dictionary.py` y activar `ENABLE_DEMO_DATA`/routing estructurado.
5. **Voz de mayor calidad**: reemplazar Web Speech API por STT/TTS en streaming del lado del servidor (WebSocket).
6. **Avatar animado** (lip sync real) cuando esté el diseño definitivo de Osky.
7. **Despliegue**: servir `frontend/dist` detrás del mismo dominio que la API, con HTTPS (requerido para el micrófono fuera de localhost).
