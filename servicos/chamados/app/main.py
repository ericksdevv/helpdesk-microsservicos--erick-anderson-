"""Microsserviço de Chamados do HelpDesk TI."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import clientes, config, dados_exemplo, eventos
from app.chamados.rotas import router as chamados_router
from app.config import DOCS_ATIVA
from app.database import Base, SessionLocal, engine, get_db
from app.erros import NaoAutenticado, NaoEncontrado, RegraDeNegocio, SemPermissao, ServicoIndisponivel
from app.seguranca_http import CabecalhosDeSeguranca

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("helpdesk.chamados")


async def _relay_outbox():
    """Reenvia eventos da Outbox que aguardavam o Redis voltar ao ar."""
    while True:
        try:
            with SessionLocal() as db:
                await asyncio.to_thread(eventos.publicar_pendentes, db)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("Erro no relay de Outbox: %s", exc)
        await asyncio.sleep(config.OUTBOX_INTERVALO_SEGUNDOS)


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    Base.metadata.create_all(engine)
    if os.getenv("DADOS_EXEMPLO", "1") == "1":
        with SessionLocal() as db:
            dados_exemplo.carregar(db)
    tarefa_outbox = None
    if config.REDIS_URL:
        tarefa_outbox = asyncio.create_task(_relay_outbox())
    try:
        yield
    finally:
        if tarefa_outbox is not None:
            tarefa_outbox.cancel()
            try:
                await tarefa_outbox
            except asyncio.CancelledError:
                pass
        clientes.fechar_cliente_http()


app = FastAPI(
    title="HelpDesk TI · Serviço de Chamados",
    version="2.0.0",
    lifespan=ciclo_de_vida,
    docs_url="/docs" if DOCS_ATIVA else None,
    redoc_url=None,
    openapi_url="/openapi.json" if DOCS_ATIVA else None,
)
app.add_middleware(CabecalhosDeSeguranca)
app.include_router(chamados_router)


@app.exception_handler(NaoEncontrado)
def tratar_nao_encontrado(request: Request, erro: NaoEncontrado):
    return JSONResponse(status_code=404, content={"detail": str(erro)})


@app.exception_handler(RegraDeNegocio)
def tratar_regra(request: Request, erro: RegraDeNegocio):
    return JSONResponse(status_code=422, content={"detail": str(erro)})


@app.exception_handler(SemPermissao)
def tratar_sem_permissao(request: Request, erro: SemPermissao):
    return JSONResponse(status_code=403, content={"detail": str(erro)})


@app.exception_handler(NaoAutenticado)
def tratar_nao_autenticado(request: Request, erro: NaoAutenticado):
    return JSONResponse(status_code=401, content={"detail": str(erro)})


@app.exception_handler(ServicoIndisponivel)
def tratar_servico_indisponivel(request: Request, erro: ServicoIndisponivel):
    return JSONResponse(status_code=503, content={"detail": str(erro)})


@app.exception_handler(IntegrityError)
def tratar_conflito(request: Request, erro: IntegrityError):
    return JSONResponse(status_code=409, content={"detail": "O registro conflita com outro já existente."})


@app.get("/saude", tags=["Saúde"])
def saude(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        banco_ok = True
    except Exception:
        banco_ok = False
    fila_info = eventos.status_fila(db)
    payload = {
        "status": "ok" if banco_ok else "indisponivel",
        "servico": "chamados",
        "banco": "ok" if banco_ok else "erro",
        "dependencias": clientes.estado_dependencias(),
        **fila_info,
    }
    return JSONResponse(status_code=200 if banco_ok else 503, content=payload)
