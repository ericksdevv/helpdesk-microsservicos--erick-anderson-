"""API Gateway do HelpDesk TI: ponto único de entrada, tela web e saúde agregada."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse

from app import proxy
from app.config import DOCS_ATIVA
from app.seguranca_http import CabecalhosDeSeguranca

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
WEB = Path(__file__).parent / "web"


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    try:
        yield
    finally:
        await proxy.fechar_cliente_http()


app = FastAPI(
    title="HelpDesk TI · API Gateway",
    version="2.0.0",
    lifespan=ciclo_de_vida,
    docs_url="/docs" if DOCS_ATIVA else None,
    redoc_url=None,
    openapi_url="/openapi.json" if DOCS_ATIVA else None,
)
app.add_middleware(CabecalhosDeSeguranca)


@app.get("/saude", tags=["Saúde"])
async def saude():
    return await proxy.saude_agregada()


@app.get("/", include_in_schema=False)
def tela_inicial():
    return FileResponse(WEB / "index.html")


@app.get("/app.js", include_in_schema=False)
def script():
    return FileResponse(WEB / "app.js", media_type="text/javascript")


@app.get("/estilo.css", include_in_schema=False)
def estilo():
    return FileResponse(WEB / "estilo.css", media_type="text/css")


@app.api_route("/{caminho:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
async def proxy_rotas(request: Request):
    return await proxy.encaminhar(request)
