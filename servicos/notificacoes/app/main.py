"""Microsserviço de Notificações orientado a eventos do HelpDesk TI."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

import redis
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import config, consumidor
from app.config import DOCS_ATIVA
from app.database import Base, SessionLocal, engine, get_db
from app.notificacoes import servico
from app.notificacoes.rotas import router as notificacoes_router
from app.seguranca_http import CabecalhosDeSeguranca

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("helpdesk.notificacoes")


async def _loop_consumidor():
    cliente: redis.Redis | None = None
    while True:
        try:
            if cliente is None:
                cliente = consumidor.obter_redis()
                if cliente is None:
                    return
                await asyncio.to_thread(consumidor.garantir_grupo, cliente)
                consumidor.definir_ativo(True)

            with SessionLocal() as db:
                await asyncio.to_thread(consumidor.consumir_lote, cliente, db, 1000)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            consumidor.definir_ativo(False)
            log.warning("Consumidor de notificações aguardando Redis: %s", exc)
            if cliente is not None:
                try:
                    cliente.close()
                except Exception:
                    pass
                cliente = None
            await asyncio.sleep(2.0)


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    Base.metadata.create_all(engine)
    tarefa = None
    if config.REDIS_URL and os.getenv("CONSUMIDOR_ATIVO", "1") == "1":
        tarefa = asyncio.create_task(_loop_consumidor())
    try:
        yield
    finally:
        consumidor.definir_ativo(False)
        if tarefa is not None:
            tarefa.cancel()
            try:
                await tarefa
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="HelpDesk TI · Serviço de Notificações",
    version="2.0.0",
    lifespan=ciclo_de_vida,
    docs_url="/docs" if DOCS_ATIVA else None,
    redoc_url=None,
    openapi_url="/openapi.json" if DOCS_ATIVA else None,
)
app.add_middleware(CabecalhosDeSeguranca)
app.include_router(notificacoes_router)


@app.get("/saude", tags=["Saúde"])
def saude(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        banco_ok = True
        processados = servico.contar_processados(db)
    except Exception:
        banco_ok = False
        processados = 0
    info_fila = consumidor.status_consumidor()
    payload = {
        "status": "ok" if banco_ok else "indisponivel",
        "servico": "notificacoes",
        "banco": "ok" if banco_ok else "erro",
        "eventos_processados": processados,
        **info_fila,
    }
    return JSONResponse(status_code=200 if banco_ok else 503, content=payload)
