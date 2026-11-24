"""Clientes HTTP resilientes (timeout, retry em conexão e Circuit Breaker) para Usuários e Inventário."""
import logging
import threading
import time

import httpx

from app import config
from app.erros import NaoAutenticado, NaoEncontrado, RegraDeNegocio, SemPermissao, ServicoIndisponivel
from app.seguranca_http import request_id_ctx

log = logging.getLogger("helpdesk.chamados.clientes")


class CircuitBreaker:
    """Disjuntor simples por dependência para evitar falhas em cascata."""

    def __init__(self, nome: str):
        self.nome = nome
        self._trava = threading.Lock()
        self._estado = "closed"
        self._falhas = 0
        self._aberto_em = 0.0

    def estado_atual(self) -> str:
        with self._trava:
            if self._estado == "open" and (time.monotonic() - self._aberto_em) >= config.CIRCUIT_BREAKER_RESET_SEGUNDOS:
                return "half_open"
            return self._estado

    def antes_de_chamar(self) -> None:
        with self._trava:
            if self._estado == "open":
                decorrido = time.monotonic() - self._aberto_em
                if decorrido < config.CIRCUIT_BREAKER_RESET_SEGUNDOS:
                    raise ServicoIndisponivel(
                        f"Serviço de {self.nome} temporariamente indisponível (circuito aberto)."
                    )
                self._estado = "half_open"

    def registrar_sucesso(self) -> None:
        with self._trava:
            self._falhas = 0
            self._estado = "closed"

    def registrar_falha(self) -> None:
        with self._trava:
            self._falhas += 1
            if self._estado == "half_open" or self._falhas >= config.CIRCUIT_BREAKER_LIMITE_FALHAS:
                if self._estado != "open":
                    log.warning("Circuito aberto para dependência=%s apos=%s falhas", self.nome, self._falhas)
                self._estado = "open"
                self._aberto_em = time.monotonic()

    def resetar(self) -> None:
        with self._trava:
            self._falhas = 0
            self._estado = "closed"
            self._aberto_em = 0.0


breaker_usuarios = CircuitBreaker("Usuários")
breaker_inventario = CircuitBreaker("Inventário")

_cliente_http: httpx.Client | None = None
_trava_http = threading.Lock()


def obter_cliente_http() -> httpx.Client:
    global _cliente_http
    with _trava_http:
        if _cliente_http is None or _cliente_http.is_closed:
            _cliente_http = httpx.Client(timeout=config.HTTP_TIMEOUT_SEGUNDOS)
        return _cliente_http


def fechar_cliente_http() -> None:
    global _cliente_http
    with _trava_http:
        if _cliente_http is not None and not _cliente_http.is_closed:
            _cliente_http.close()
            _cliente_http = None


def _get_com_resiliencia(url: str, token_bearer: str, breaker: CircuitBreaker) -> httpx.Response:
    breaker.antes_de_chamar()
    headers = {
        "Authorization": f"Bearer {token_bearer}",
        "X-Request-ID": request_id_ctx.get(),
    }
    cliente = obter_cliente_http()

    for tentativa in (0, 1):
        try:
            resposta = cliente.get(url, headers=headers)
        except httpx.TimeoutException as exc:
            breaker.registrar_falha()
            log.warning("Timeout ao consultar %s (%s): %s", breaker.nome, url, exc)
            raise ServicoIndisponivel(
                f"Serviço de {breaker.nome} demorou para responder. Tente novamente em instantes."
            ) from exc
        except httpx.ConnectError as exc:
            if tentativa == 0:
                time.sleep(0.05)
                continue
            breaker.registrar_falha()
            log.warning("Falha de conexão com %s (%s): %s", breaker.nome, url, exc)
            raise ServicoIndisponivel(
                f"Serviço de {breaker.nome} indisponível no momento. Tente novamente em instantes."
            ) from exc
        except httpx.RequestError as exc:
            breaker.registrar_falha()
            log.warning("Erro de rede ao consultar %s (%s): %s", breaker.nome, url, exc)
            raise ServicoIndisponivel(
                f"Serviço de {breaker.nome} indisponível no momento. Tente novamente em instantes."
            ) from exc

        if resposta.status_code >= 500:
            breaker.registrar_falha()
            raise ServicoIndisponivel(
                f"Serviço de {breaker.nome} indisponível no momento (erro {resposta.status_code})."
            )

        breaker.registrar_sucesso()
        if resposta.status_code == 401:
            raise NaoAutenticado("Sessão inválida ou expirada.")
        if resposta.status_code == 403:
            raise SemPermissao("Você não tem permissão para consultar este recurso.")
        return resposta

    breaker.registrar_falha()
    raise ServicoIndisponivel(f"Serviço de {breaker.nome} indisponível no momento.")


def verificar_ativo(ativo_id: int, token_bearer: str) -> dict:
    url = f"{config.INVENTARIO_URL}/ativos/{ativo_id}"
    resposta = _get_com_resiliencia(url, token_bearer, breaker_inventario)
    if resposta.status_code == 404:
        raise NaoEncontrado(f"Ativo {ativo_id} não encontrado.")
    if not resposta.is_success:
        raise ServicoIndisponivel("Falha inesperada ao consultar o serviço de Inventário.")
    return resposta.json()


def obter_tecnico(tecnico_id: int, token_bearer: str) -> dict:
    url = f"{config.USUARIOS_URL}/usuarios/{tecnico_id}"
    resposta = _get_com_resiliencia(url, token_bearer, breaker_usuarios)
    if resposta.status_code == 404:
        raise NaoEncontrado(f"Usuário {tecnico_id} não encontrado.")
    if not resposta.is_success:
        raise ServicoIndisponivel("Falha inesperada ao consultar o serviço de Usuários.")
    usuario = resposta.json()
    if usuario.get("perfil") != "tecnico":
        raise RegraDeNegocio(f"Usuário {tecnico_id} não é técnico.")
    return usuario


def estado_dependencias() -> dict[str, dict[str, str]]:
    return {
        "usuarios": {"circuito": breaker_usuarios.estado_atual()},
        "inventario": {"circuito": breaker_inventario.estado_atual()},
    }
