"""Contract between the agent and enterprise data (see docs/DATA_DICTIONARY.md).

Only datasets, fields and operations declared here can be queried.
"""

DATA_DICTIONARY = {
    "customers": {
        "label": ("cliente", "clientes"),
        "operations": {"count", "list"},
        "display_fields": ["name", "city"],
        "fields": {
            "id": {"type": "string", "label": "identificador"},
            "name": {"type": "string", "label": "nombre", "match_values": True},
            "city": {"type": "string", "label": "ciudad", "match_values": True, "group_words": ["ciudad", "ciudades"]},
            "status": {
                "type": "string",
                "label": "estado",
                "group_words": ["estado", "estados"],
                "value_synonyms": {
                    "active": ["activo", "activos", "activa", "activas"],
                    "inactive": ["inactivo", "inactivos", "inactiva", "inactivas"],
                },
                "value_labels": {"active": "activo", "inactive": "inactivo"},
            },
        },
    },
    "sales": {
        "label": ("venta", "ventas"),
        "operations": {"count", "sum", "avg", "min", "max", "list"},
        "default_measure": "amount",
        "display_fields": ["id", "seller", "amount", "sale_date"],
        "fields": {
            "id": {"type": "string", "label": "identificador"},
            "customer_id": {"type": "string", "label": "cliente", "group_words": ["cliente", "clientes"]},
            "seller": {"type": "string", "label": "vendedor", "match_values": True, "group_words": ["vendedor", "vendedores", "vendedora", "vendedoras"]},
            "amount": {"type": "decimal", "label": "valor", "currency": True},
            "sale_date": {"type": "date", "label": "fecha", "group_words": ["fecha", "fechas", "dia", "dias"]},
        },
    },
}

NUMERIC_TYPES = {"decimal", "integer"}
