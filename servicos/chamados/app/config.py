"""Configurações do microsserviço de Chamados."""
import logging
import os
import secrets
from pathlib import Path

log = logging.getLogger("helpdesk.chamados")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./chamados.db")


def _carregar_segredo() -> str:
    segredo = (os.getenv("JWT_SEGREDO") or "").strip()
    arquivo_segredo = (os.getenv("JWT_SEGREDO_FILE") or "").strip()
    if len(segredo) < 32 and arquivo_segredo:
        caminho = Path(arquivo_segredo)
        if caminho.is_file():
            segredo = caminho.read_text(encoding="utf-8").strip()
    if len(segredo) < 32:
        if segredo:
            log.warning("JWT_SEGREDO tem menos de 32 caracteres; usando segredo aleatório em memória.")
        else:
            log.warning("JWT_SEGREDO não definido; usando segredo aleatório em memória.")
        return secrets.token_urlsafe(48)
    return segredo


JWT_SEGREDO = _carregar_segredo()
JWT_ALGORITMO = "HS256"
JWT_EMISSOR = "helpdesk-ti"

USUARIOS_URL = os.getenv("USUARIOS_URL", "http://usuarios:8000").rstrip("/")
INVENTARIO_URL = os.getenv("INVENTARIO_URL", "http://inventario:8000").rstrip("/")
REDIS_URL = (os.getenv("REDIS_URL") or "").strip()
EVENTOS_STREAM = os.getenv("EVENTOS_STREAM", "helpdesk:eventos")

HTTP_TIMEOUT_SEGUNDOS = float(os.getenv("HTTP_TIMEOUT_SEGUNDOS", "2.5"))
CIRCUIT_BREAKER_LIMITE_FALHAS = int(os.getenv("CIRCUIT_BREAKER_LIMITE_FALHAS", "2"))
CIRCUIT_BREAKER_RESET_SEGUNDOS = float(os.getenv("CIRCUIT_BREAKER_RESET_SEGUNDOS", "5.0"))
OUTBOX_INTERVALO_SEGUNDOS = float(os.getenv("OUTBOX_INTERVALO_SEGUNDOS", "2.0"))

TAMANHO_MAXIMO_REQUISICAO = 64 * 1024
DOCS_ATIVA = os.getenv("DOCS", "1") == "1"
