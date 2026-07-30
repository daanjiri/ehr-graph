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

ANTHROPIC_MODEL = os.environ.get(
    "ANTHROPIC_MODEL",
    "claude-haiku-4-5-20251001",
)
ANTHROPIC_MAX_TOKENS = entero_entorno("ANTHROPIC_MAX_TOKENS", 800)

CHAT_MAX_CHARS = entero_entorno("CHAT_MAX_CHARS", 500)
CHAT_MAX_INTERCAMBIOS = entero_entorno("CHAT_MAX_INTERCAMBIOS", 3)
CHAT_LIMITE_DIARIO_CLIENTE = entero_entorno("CHAT_LIMITE_DIARIO_CLIENTE", 3)
CHAT_LIMITE_MENSUAL_GLOBAL = entero_entorno("CHAT_LIMITE_MENSUAL_GLOBAL", 100)
CHAT_RATE_SALT = os.environ.get("CHAT_RATE_SALT", "solo-desarrollo-local")

KEEPALIVE_TOKEN = os.environ.get("KEEPALIVE_TOKEN", "")

if (
    os.environ.get("ANTHROPIC_API_KEY")
    and CHAT_RATE_SALT == "solo-desarrollo-local"
):
    raise RuntimeError(
        "CHAT_RATE_SALT debe configurarse antes de habilitar el chat"
    )
