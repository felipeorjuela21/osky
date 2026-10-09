# Arquitectura

```text
                 USER
                  |
             microphone
                  |
              STT layer
                  |
                  v
        +--------------------+
        | Query Interpreter  |
        |                    |
        | text -> intent     |
        | -> structured query|
        +---------+----------+
                  |
                  v
        +--------------------+
        | Query Validator    |
        +---------+----------+
                  |
                  v
        +--------------------+
        | Query Engine       |
        +---------+----------+
                  |
                  v
        +--------------------+
        | Enterprise Data   |
        | PostgreSQL/SQLSrv |
        +---------+----------+
                  |
                  v
        +--------------------+
        | Deterministic      |
        | Response Builder  |
        +---------+----------+
                  |
                 TTS
                  |
                Avatar
```

## Separación crítica

### Interpretación
Puede usar IA en una fase posterior.

### Ejecución
Código determinístico y validado.

### Respuesta
Construida desde el resultado real.

Nunca se debe permitir que el modelo genere directamente una cifra empresarial y se presente como fuente de verdad.

## Voz

Cuando se agregue voz:

```text
Browser
  |
  | WebSocket
  v
FastAPI
  |
  +--> STT streaming
  |
  +--> Query Engine
  |
  +--> Response Builder
  |
  +--> TTS streaming
```

## Avatar

El frontend manejará estados:

- idle
- listening
- thinking
- speaking
- error

La animación se sincronizará con el audio en una fase posterior.
