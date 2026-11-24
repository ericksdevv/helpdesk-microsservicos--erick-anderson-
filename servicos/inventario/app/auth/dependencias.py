"""Dependências do FastAPI para validar token JWT e perfil no serviço de Inventário."""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import tokens
from app.auth.tokens import UsuarioAutenticado

esquema = HTTPBearer(auto_error=False)

NAO_AUTENTICADO = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Faça login para continuar.",
    headers={"WWW-Authenticate": "Bearer"},
)


def usuario_atual(
    credenciais: HTTPAuthorizationCredentials | None = Depends(esquema),
) -> UsuarioAutenticado:
    if credenciais is None or credenciais.scheme.lower() != "bearer":
        raise NAO_AUTENTICADO
    try:
        return tokens.ler(credenciais.credentials)
    except tokens.TokenInvalido:
        raise NAO_AUTENTICADO


def exigir_perfil(*perfis: str):
    def verificar(usuario: UsuarioAutenticado = Depends(usuario_atual)) -> UsuarioAutenticado:
        if usuario.perfil not in perfis:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Você não tem permissão para esta ação.")
        return usuario

    return verificar
