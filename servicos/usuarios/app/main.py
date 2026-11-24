"""Microsserviço de Usuários e Autenticação do HelpDesk TI."""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app import dados_exemplo
from app.auth import limite
from app.auth.rotas import router as auth_router
from app.config import DOCS_ATIVA
from app.database import Base, SessionLocal, engine, verificar_saude
from app.erros import NaoEncontrado, RegraDeNegocio, SemPermissao
from app.seguranca_http import CabecalhosDeSeguranca
from app.usuarios.rotas import router as usuarios_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    """Cria as tabelas do banco de usuários e popula exemplos na primeira execução."""
    Base.metadata.create_all(engine)
    if os.getenv("DADOS_EXEMPLO", "1") == "1":
        with SessionLocal() as db:
            dados_exemplo.carregar(db)
    yield


app = FastAPI(
    title="HelpDesk TI · Serviço de Usuários",
    version="2.0.0",
    lifespan=ciclo_de_vida,
    docs_url="/docs" if DOCS_ATIVA else None,
    redoc_url=None,
    openapi_url="/openapi.json" if DOCS_ATIVA else None,
)
app.add_middleware(CabecalhosDeSeguranca)

app.include_router(auth_router)
app.include_router(usuarios_router)


@app.exception_handler(NaoEncontrado)
def tratar_nao_encontrado(request: Request, erro: NaoEncontrado):
    return JSONResponse(status_code=404, content={"detail": str(erro)})


@app.exception_handler(RegraDeNegocio)
def tratar_regra(request: Request, erro: RegraDeNegocio):
    return JSONResponse(status_code=422, content={"detail": str(erro)})


@app.exception_handler(SemPermissao)
def tratar_sem_permissao(request: Request, erro: SemPermissao):
    return JSONResponse(status_code=403, content={"detail": str(erro)})


@app.exception_handler(IntegrityError)
def tratar_conflito(request: Request, erro: IntegrityError):
    return JSONResponse(status_code=409, content={"detail": "O registro conflita com outro já existente."})


@app.get("/saude", tags=["Saúde"])
def saude():
    banco_ok = verificar_saude()
    payload = {
        "status": "ok" if banco_ok else "indisponivel",
        "servico": "usuarios",
        "banco": "ok" if banco_ok else "erro",
        "rate_limit": limite.status_armazenamento(),
    }
    return JSONResponse(status_code=200 if banco_ok else 503, content=payload)
