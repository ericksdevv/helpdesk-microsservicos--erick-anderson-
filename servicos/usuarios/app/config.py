"""Configurações do microsserviço de Usuários e Autenticação."""
import logging
import os
import secrets
from pathlib import Path

log = logging.getLogger("helpdesk.usuarios")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./usuarios.db")


def _carregar_segredo() -> str:
    """Lê JWT_SEGREDO da variável de ambiente ou de arquivo montado em volume."""
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
TOKEN_MINUTOS = int(os.getenv("TOKEN_MINUTOS", "60"))

# Proteção contra tentativas de adivinhar senhas
LOGIN_MAX_FALHAS = int(os.getenv("LOGIN_MAX_FALHAS", "5"))
LOGIN_JANELA_SEGUNDOS = int(os.getenv("LOGIN_JANELA_SEGUNDOS", "300"))
REDIS_URL = (os.getenv("REDIS_URL") or "").strip()

TAMANHO_MAXIMO_REQUISICAO = 64 * 1024
DOCS_ATIVA = os.getenv("DOCS", "1") == "1"
