"""Cuotas persistentes de la demo pública sin guardar direcciones IP."""

import hashlib
import hmac
from datetime import datetime, timezone

from config import (CHAT_LIMITE_DIARIO_CLIENTE, CHAT_LIMITE_MENSUAL_GLOBAL,
                    CHAT_RATE_SALT)


Q_ESQUEMA = """
CREATE CONSTRAINT demo_usage_key IF NOT EXISTS
FOR (u:DemoUsage) REQUIRE u.key IS UNIQUE
"""

Q_RESERVAR = """
MERGE (g:DemoUsage {key: $global_key})
ON CREATE SET g.count = 0, g.periodo = $mes, g.tipo = 'global-mes'
MERGE (c:DemoUsage {key: $client_key})
ON CREATE SET c.count = 0, c.periodo = $dia, c.tipo = 'cliente-dia'
// Escribir antes de leer fuerza locks en orden global -> cliente.
SET g._rate_lock = true
SET c._rate_lock = true
WITH g, c,
     coalesce(g.count, 0) < $global_limit
     AND coalesce(c.count, 0) < $client_limit AS permitido
FOREACH (_ IN CASE WHEN permitido THEN [1] ELSE [] END |
  SET g.count = coalesce(g.count, 0) + 1,
      c.count = coalesce(c.count, 0) + 1,
      g.actualizado_en = datetime(),
      c.actualizado_en = datetime()
)
REMOVE g._rate_lock, c._rate_lock
RETURN permitido, g.count AS global_count, c.count AS client_count
"""


def hash_cliente(direccion: str) -> str:
    """HMAC estable para limitar uso sin persistir la IP en claro."""
    return hmac.new(
        CHAT_RATE_SALT.encode("utf-8"),
        direccion.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def direccion_cliente(request) -> str:
    """Obtiene el primer hop declarado por el proxy de Railway."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "desconocido"


def asegurar_esquema(driver) -> None:
    with driver.session() as sesion:
        sesion.run(Q_ESQUEMA).consume()


def reservar(driver, client_hash: str, ahora=None) -> dict:
    """Reserva una interacción de forma transaccional y devuelve los conteos."""
    ahora = ahora or datetime.now(timezone.utc)
    dia = ahora.strftime("%Y-%m-%d")
    mes = ahora.strftime("%Y-%m")
    with driver.session() as sesion:
        fila = sesion.run(
            Q_RESERVAR,
            global_key=f"global:{mes}",
            client_key=f"cliente:{dia}:{client_hash}",
            dia=dia,
            mes=mes,
            global_limit=CHAT_LIMITE_MENSUAL_GLOBAL,
            client_limit=CHAT_LIMITE_DIARIO_CLIENTE,
        ).single(strict=True)
    return dict(fila)
