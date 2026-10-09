# Alcance del proyecto

## Visión

Construir un agente de voz empresarial que responda exclusivamente preguntas relacionadas con información interna autorizada.

## Lo que SÍ hará

- Consultar datos estructurados.
- Responder métricas.
- Filtrar información.
- Agrupar información.
- Buscar registros.
- Consultar múltiples fuentes en fases posteriores.
- Hablar por voz.
- Mantener un personaje visual.
- Auditar consultas.
- Respetar permisos.

## Lo que NO hará

- Chat general.
- Inventar información.
- Completar datos faltantes con conocimiento externo.
- Ejecutar SQL arbitrario.
- Acceder a fuentes no autorizadas.
- Modificar datos en el MVP.

## Regla de oro

> Si la respuesta no puede demostrarse a partir de una fuente empresarial autorizada, el agente no debe afirmar el dato como verdadero.

## Roadmap

### Sprint 1
Excel/CSV -> PostgreSQL -> Query Engine.

### Sprint 2
Data Dictionary + validaciones + filtros/agrupaciones.

### Sprint 3
Parser de lenguaje natural -> consulta estructurada.

### Sprint 4
STT/TTS + WebSocket.

### Sprint 5
Avatar + lip sync.

### Sprint 6
SQL Server/APIs/ERP + permisos + auditoría.
