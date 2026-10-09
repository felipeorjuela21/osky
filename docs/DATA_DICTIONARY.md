# Data Dictionary

Este archivo es el contrato entre el agente y los datos empresariales.

## customers

| Campo | Tipo | Descripción | Sensible |
|---|---|---|---|
| id | string | Identificador único | No |
| name | string | Nombre del cliente | No |
| city | string | Ciudad | No |
| status | string | Estado del cliente | No |

Operaciones MVP:
- COUNT
- FILTER
- SEARCH

## sales

| Campo | Tipo | Descripción | Sensible |
|---|---|---|---|
| id | string | Identificador de venta | No |
| customer_id | string | Cliente asociado | No |
| seller | string | Vendedor | No |
| amount | decimal | Valor de la venta | No |
| sale_date | date | Fecha de venta | No |

Operaciones MVP:
- COUNT
- SUM
- AVG
- FILTER
- GROUP BY

## Próxima evolución

El Data Dictionary debe convertirse posteriormente en tablas de metadata:

datasets
dataset_fields
dataset_permissions
dataset_operations
dataset_synonyms
