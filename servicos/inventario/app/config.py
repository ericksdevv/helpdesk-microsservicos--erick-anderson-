"""Configurações do microsserviço de Inventário."""
import logging
import os
import secrets
from pathlib import Path

log = logging.getLogger("helpdesk.inventario")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./inventario.db")


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
TAMANHO_MAXIMO_REQUISICAO = 64 * 1024
DOCS_ATIVA = os.getenv("DOCS", "1") == "1"
