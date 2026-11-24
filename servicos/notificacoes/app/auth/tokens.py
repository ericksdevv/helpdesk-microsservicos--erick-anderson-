"""Validação stateless de tokens JWT no serviço de Notificações."""
from dataclasses import dataclass

import jwt

from app.config import JWT_ALGORITMO, JWT_EMISSOR, JWT_SEGREDO

PERFIS_VALIDOS = frozenset({"solicitante", "tecnico", "admin"})


class TokenInvalido(Exception):
    pass


@dataclass(frozen=True)
class UsuarioAutenticado:
    id: int
    perfil: str


def ler(token: str) -> UsuarioAutenticado:
    try:
        dados = jwt.decode(
            token,
            JWT_SEGREDO,
            algorithms=[JWT_ALGORITMO],
            issuer=JWT_EMISSOR,
            options={"require": ["exp", "iat", "sub", "iss", "perfil"]},
        )
        perfil = dados["perfil"]
        if perfil not in PERFIS_VALIDOS:
            raise TokenInvalido()
        return UsuarioAutenticado(id=int(dados["sub"]), perfil=perfil)
    except (jwt.PyJWTError, ValueError, KeyError) as erro:
        raise TokenInvalido() from erro
