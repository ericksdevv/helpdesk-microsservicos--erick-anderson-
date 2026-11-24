"""Configurações do microsserviço de Notificações."""
import logging
import os
import secrets
from pathlib import Path

log = logging.getLogger("helpdesk.notificacoes")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./notificacoes.db")


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

REDIS_URL = (os.getenv("REDIS_URL") or "").strip()
EVENTOS_STREAM = os.getenv("EVENTOS_STREAM", "helpdesk:eventos")
EVENTOS_DLQ = os.getenv("EVENTOS_DLQ", "helpdesk:eventos:dlq")
EVENTOS_GRUPO = os.getenv("EVENTOS_GRUPO", "notificacoes-workers")
CONSUMIDOR_NOME = os.getenv("HOSTNAME", "worker-1")
MAX_TENTATIVAS_EVENTO = int(os.getenv("MAX_TENTATIVAS_EVENTO", "3"))

TAMANHO_MAXIMO_REQUISICAO = 64 * 1024
DOCS_ATIVA = os.getenv("DOCS", "1") == "1"
