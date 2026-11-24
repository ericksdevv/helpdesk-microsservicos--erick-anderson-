from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import proxy
from app.main import app


@pytest.fixture
def cliente():
    with TestClient(app) as c:
        yield c


def test_tela_estatica_e_cabecalhos_de_seguranca(cliente):
    r = cliente.get("/")
    assert r.status_code == 200
    assert "HelpDesk TI" in r.text
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def test_tela_escapa_html_e_sem_onclick():
    js = (Path(__file__).parent.parent / "app" / "web" / "app.js").read_text(encoding="utf-8")
    assert "const esc =" in js and "onclick" not in js


def test_roteamento_de_prefixos():
    assert proxy.resolver_destino("/auth/login")[0] == "usuarios"
    assert proxy.resolver_destino("/usuarios/2")[0] == "usuarios"
    assert proxy.resolver_destino("/ativos")[0] == "inventario"
    assert proxy.resolver_destino("/chamados/painel")[0] == "chamados"
    assert proxy.resolver_destino("/notificacoes")[0] == "notificacoes"
    assert proxy.resolver_destino("/usuarios_falso") is None


def test_proxy_encaminha_headers_e_trata_servico_offline(monkeypatch, cliente):
    captura = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captura["url"] = str(request.url)
        captura["auth"] = request.headers.get("authorization")
        captura["req_id"] = request.headers.get("x-request-id")
        if request.url.path.startswith("/ativos"):
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json=[{"id": 1, "titulo": "Teste"}])

    async_mock = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(proxy, "obter_cliente_http", lambda: async_mock)

    ok = cliente.get("/chamados?status=aberto", headers={"Authorization": "Bearer abc", "X-Request-ID": "gw_123"})
    assert ok.status_code == 200
    assert ok.headers["x-request-id"] == "gw_123"
    assert captura["auth"] == "Bearer abc"
    assert captura["req_id"] == "gw_123"
    assert "status=aberto" in captura["url"]

    offline = cliente.get("/ativos")
    assert offline.status_code == 503
    assert offline.json()["servico"] == "inventario"


def test_saude_agregada_mostra_servico_offline(monkeypatch, cliente):
    async def handler(request: httpx.Request) -> httpx.Response:
        if "inventario" in str(request.url):
            raise httpx.ConnectError("offline")
        return httpx.Response(200, json={"status": "ok"})

    async_mock = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(proxy, "obter_cliente_http", lambda: async_mock)

    r = cliente.get("/saude")
    assert r.status_code == 200
    dados = r.json()
    assert dados["status"] == "degradado"
    assert dados["servicos"]["usuarios"]["status"] == "ok"
    assert dados["servicos"]["inventario"]["status"] == "offline"
    assert dados["servicos"]["chamados"]["status"] == "ok"
    assert dados["servicos"]["notificacoes"]["status"] == "ok"


def test_limite_de_payload_e_rota_desconhecida(cliente):
    assert cliente.get("/inexistente").status_code == 404
    grande = '{"a": "' + ("x" * 70000) + '"}'
    assert cliente.post("/chamados", headers={"Content-Type": "application/json"}, content=grande).status_code == 413
