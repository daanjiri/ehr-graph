"""Servidor FastAPI de la UI web: grafo (travesias fijas) + chat SSE.

Arranque:  uvicorn api.main:app --port 8000   (1 solo worker: sesiones in-memory)
"""

import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agente import driver
from api import chat, grafo


def _calentar_embeddings():
    """Carga el modelo de embeddings en background para que el primer
    buscar_semantico del chat no pague los ~10-30s de carga."""
    import semantica
    semantica.modelo()


@asynccontextmanager
async def lifespan(app):
    driver().verify_connectivity()
    threading.Thread(target=_calentar_embeddings, daemon=True).start()
    yield
    driver().close()


app = FastAPI(title="ehr-graph UI", lifespan=lifespan)
app.include_router(grafo.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
