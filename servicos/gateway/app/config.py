"""Configurações do API Gateway do HelpDesk TI."""
import os

USUARIOS_URL = os.getenv("USUARIOS_URL", "http://usuarios:8000").rstrip("/")
INVENTARIO_URL = os.getenv("INVENTARIO_URL", "http://inventario:8000").rstrip("/")
CHAMADOS_URL = os.getenv("CHAMADOS_URL", "http://chamados:8000").rstrip("/")
NOTIFICACOES_URL = os.getenv("NOTIFICACOES_URL", "http://notificacoes:8000").rstrip("/")

GATEWAY_TIMEOUT_SEGUNDOS = float(os.getenv("GATEWAY_TIMEOUT_SEGUNDOS", "5.0"))
SAUDE_TIMEOUT_SEGUNDOS = float(os.getenv("SAUDE_TIMEOUT_SEGUNDOS", "1.5"))

TAMANHO_MAXIMO_REQUISICAO = 64 * 1024
DOCS_ATIVA = os.getenv("DOCS", "1") == "1"
