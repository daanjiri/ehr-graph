"""Servidor FastAPI de la UI web: grafo (travesías fijas) + chat SSE.

Arranque local: uvicorn api.main:app --port 8010 (un solo worker).
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from neo4j.exceptions import ServiceUnavailable, SessionExpired

from agente import driver
from api import chat, grafo, operacion
from api.limites import asegurar_esquema

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    try:
        driver().verify_connectivity()
        asegurar_esquema(driver())
    except Exception:
        # La UI y /health deben poder arrancar mientras Aura es reanudada.
        logger.exception("Neo4j no estaba disponible durante el arranque")
    yield
    driver().close()


app = FastAPI(title="ehr-graph UI", lifespan=lifespan)
app.include_router(operacion.router, prefix="/api")
app.include_router(grafo.router, prefix="/api")
app.include_router(chat.router, prefix="/api")


async def base_no_disponible(_request, _exc):
    return JSONResponse(
        status_code=503,
        content={"detail": "La base de datos no está disponible temporalmente"},
    )


app.add_exception_handler(ServiceUnavailable, base_no_disponible)
app.add_exception_handler(SessionExpired, base_no_disponible)

# En producción el Dockerfile copia el build de Vite aquí. En desarrollo Vite
# sigue sirviendo la UI y usando su proxy /api.
DIST_UI = Path(__file__).resolve().parent.parent / "ui" / "dist"
if DIST_UI.is_dir():
    app.mount("/", StaticFiles(directory=DIST_UI, html=True), name="ui")
