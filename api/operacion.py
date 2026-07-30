"""Endpoints operativos pequeños para Railway y AuraDB."""

import secrets

from fastapi import APIRouter, Header, HTTPException

from agente import driver, q
from config import KEEPALIVE_TOKEN

router = APIRouter()


@router.get("/health")
def health():
    """Liveness: no toca servicios externos y sirve para el deploy de Railway."""
    return {"status": "ok"}


@router.get("/ready")
def ready():
    try:
        q("RETURN 1 AS ok")
    except Exception as exc:
        raise HTTPException(503, "La base de datos no está disponible") from exc
    return {"status": "ready"}


@router.post("/keepalive")
def keepalive(authorization: str | None = Header(default=None)):
    if not KEEPALIVE_TOKEN:
        raise HTTPException(503, "Keepalive no configurado")
    esperado = f"Bearer {KEEPALIVE_TOKEN}"
    if not authorization or not secrets.compare_digest(authorization, esperado):
        raise HTTPException(401, "Credencial inválida")
    with driver().session() as sesion:
        sesion.run("RETURN 1 AS ok").consume()
    return {"status": "ok"}
