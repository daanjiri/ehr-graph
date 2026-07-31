"""Configuración compartida para desarrollo local y despliegue.

Los valores sensibles siempre llegan por variables de entorno. Los defaults
solo apuntan al Neo4j local documentado para que los scripts existentes sigan
funcionando sin un archivo .env.
"""

import os


def entero_entorno(nombre: str, default: int, minimo: int = 1) -> int:
    try:
        return max(minimo, int(os.environ.get(nombre, default)))
    except (TypeError, ValueError):
        return default


NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password123")
NEO4J_AUTH = (NEO4J_USERNAME, NEO4J_PASSWORD)

MODELOS_ANTHROPIC = (
    {
        "id": "claude-haiku-4-5-20251001",
        "nombre": "Claude Haiku 4.5",
        "descripcion": "Rápido y económico",
        "nivel_costo": "bajo",
        "admite_esfuerzo": False,
    },
    {
        "id": "claude-sonnet-5",
        "nombre": "Claude Sonnet 5",
        "descripcion": "Equilibrio recomendado",
        "nivel_costo": "medio",
        "admite_esfuerzo": True,
    },
    {
        "id": "claude-opus-5",
        "nombre": "Claude Opus 5",
        "descripcion": "Máxima capacidad",
        "nivel_costo": "alto",
        "admite_esfuerzo": True,
    },
)
MODELOS_ANTHROPIC_POR_ID = {modelo["id"]: modelo for modelo in MODELOS_ANTHROPIC}

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
if ANTHROPIC_MODEL not in MODELOS_ANTHROPIC_POR_ID:
    raise RuntimeError("ANTHROPIC_MODEL no pertenece al catálogo permitido")

ANTHROPIC_MAX_TOKENS = entero_entorno("ANTHROPIC_MAX_TOKENS", 2000)
ANTHROPIC_EFFORT = os.environ.get("ANTHROPIC_EFFORT", "medium")
if ANTHROPIC_EFFORT not in {"low", "medium", "high"}:
    raise RuntimeError("ANTHROPIC_EFFORT debe ser low, medium o high")

CHAT_MAX_CHARS = entero_entorno("CHAT_MAX_CHARS", 500)
CHAT_MAX_INTERCAMBIOS = entero_entorno("CHAT_MAX_INTERCAMBIOS", 3)
CHAT_LIMITE_DIARIO_CLIENTE = entero_entorno("CHAT_LIMITE_DIARIO_CLIENTE", 20)
CHAT_LIMITE_MENSUAL_GLOBAL = entero_entorno("CHAT_LIMITE_MENSUAL_GLOBAL", 100)
CHAT_MAX_RONDAS_HERRAMIENTAS = entero_entorno(
    "CHAT_MAX_RONDAS_HERRAMIENTAS", 4
)
CHAT_RATE_SALT = os.environ.get("CHAT_RATE_SALT", "solo-desarrollo-local")

KEEPALIVE_TOKEN = os.environ.get("KEEPALIVE_TOKEN", "")

if (
    os.environ.get("ANTHROPIC_API_KEY")
    and CHAT_RATE_SALT == "solo-desarrollo-local"
):
    raise RuntimeError(
        "CHAT_RATE_SALT debe configurarse antes de habilitar el chat"
    )
