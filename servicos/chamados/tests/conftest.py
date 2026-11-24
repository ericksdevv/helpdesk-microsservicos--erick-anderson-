from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import clientes, config, eventos
from app.database import Base, get_db
from app.main import app


def emitir_token(usuario_id: int, perfil: str, segredo: str | None = None, expirado: bool = False) -> dict[str, str]:
    agora = datetime.now(timezone.utc)
    if expirado:
        agora = agora - timedelta(hours=2)
    payload = {
        "sub": str(usuario_id),
        "perfil": perfil,
        "iss": config.JWT_EMISSOR,
        "iat": agora,
        "exp": agora + timedelta(minutes=15),
    }
    token = jwt.encode(payload, segredo or config.JWT_SEGREDO, algorithm=config.JWT_ALGORITMO)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def fake_redis(monkeypatch):
    publicados: list[tuple[str, dict]] = []

    class FakeRedis:
        def ping(self):
            return True

        def xadd(self, stream, campos, **_kwargs):
            publicados.append((stream, campos))
            return f"{len(publicados)}-0"

    monkeypatch.setattr(config, "REDIS_URL", "redis://fake:6379/0")
    monkeypatch.setattr(eventos, "obter_redis", lambda: FakeRedis())
    return publicados


@pytest.fixture
def mock_servicos(monkeypatch):
    """Simula os microsserviços de Usuários e Inventário via HTTP, conferindo Bearer e X-Request-ID."""
    registros = {"headers_recebidos": []}
    ativos = {1: {"id": 1, "patrimonio": "PAT-1", "tipo": "computador", "descricao": "Desktop", "setor": "TI"}}
    usuarios = {
        1: {"id": 1, "nome": "Admin", "perfil": "admin"},
        2: {"id": 2, "nome": "Ana", "perfil": "solicitante"},
        3: {"id": 3, "nome": "Bia", "perfil": "solicitante"},
        4: {"id": 4, "nome": "Carla", "perfil": "tecnico"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        registros["headers_recebidos"].append(dict(request.headers))
        if not request.headers.get("authorization", "").startswith("Bearer "):
            return httpx.Response(401, json={"detail": "Sem token"})
        if request.url.path.startswith("/ativos/"):
            aid = int(request.url.path.rsplit("/", 1)[-1])
            if aid in ativos:
                return httpx.Response(200, json=ativos[aid])
            return httpx.Response(404, json={"detail": "Ativo não encontrado."})
        if request.url.path.startswith("/usuarios/"):
            uid = int(request.url.path.rsplit("/", 1)[-1])
            if uid in usuarios:
                return httpx.Response(200, json=usuarios[uid])
            return httpx.Response(404, json={"detail": "Usuário não encontrado."})
        return httpx.Response(404)

    http_mock = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(clientes, "obter_cliente_http", lambda: http_mock)
    clientes.breaker_usuarios.resetar()
    clientes.breaker_inventario.resetar()
    return registros


@pytest.fixture
def sessao(monkeypatch):
    monkeypatch.setenv("DADOS_EXEMPLO", "0")
    monkeypatch.setattr(config, "REDIS_URL", "")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Sessao = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def db_de_teste():
        db = Sessao()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = db_de_teste
    yield Sessao
    app.dependency_overrides.clear()


@pytest.fixture
def cliente(sessao, fake_redis, mock_servicos):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def contas():
    return {
        "admin": {"headers": emitir_token(1, "admin"), "id": 1},
        "ana": {"headers": emitir_token(2, "solicitante"), "id": 2},
        "bia": {"headers": emitir_token(3, "solicitante"), "id": 3},
        "carla": {"headers": emitir_token(4, "tecnico"), "id": 4},
    }
