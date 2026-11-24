"""Criação e validação dos tokens JWT."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt

from app.config import JWT_ALGORITMO, JWT_EMISSOR, JWT_SEGREDO, TOKEN_MINUTOS

PERFIS_VALIDOS = frozenset({"solicitante", "tecnico", "admin"})


class TokenInvalido(Exception):
    pass


@dataclass(frozen=True)
class DadosToken:
    usuario_id: int
    perfil: str


def criar(usuario_id: int, perfil: str) -> tuple[str, datetime]:
    agora = datetime.now(timezone.utc)
    expira = agora + timedelta(minutes=TOKEN_MINUTOS)
    dados = {"sub": str(usuario_id), "perfil": perfil, "iat": agora, "exp": expira, "iss": JWT_EMISSOR}
    return jwt.encode(dados, JWT_SEGREDO, algorithm=JWT_ALGORITMO), expira


def ler(token: str) -> DadosToken:
    """Valida assinatura, algoritmo, emissor e claims do JWT."""
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
        return DadosToken(usuario_id=int(dados["sub"]), perfil=perfil)
    except (jwt.PyJWTError, ValueError, KeyError) as erro:
        raise TokenInvalido() from erro
