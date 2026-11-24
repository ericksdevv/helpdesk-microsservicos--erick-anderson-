from datetime import datetime, timedelta, timezone

import jwt

from app import config
from tests.conftest import emitir_token


def test_tecnico_cadastra_ativo_e_filtra_por_setor(cliente, contas):
    h = contas["carla"]["headers"]
    r1 = cliente.post("/ativos", headers=h, json={"patrimonio": "PAT-1", "tipo": "impressora", "descricao": "HP", "setor": "RH"})
    r2 = cliente.post("/ativos", headers=h, json={"patrimonio": "PAT-2", "tipo": "computador", "descricao": "Dell", "setor": "TI"})
    assert r1.status_code == 201 and r2.status_code == 201
    assert len(cliente.get("/ativos", params={"setor": "RH"}, headers=h).json()) == 1
    assert cliente.get(f"/ativos/{r1.json()['id']}", headers=contas["ana"]["headers"]).status_code == 200


def test_patrimonio_duplicado_recusado(cliente, contas):
    h = contas["carla"]["headers"]
    ativo = {"patrimonio": "PAT-1", "tipo": "computador", "descricao": "Dell", "setor": "TI"}
    assert cliente.post("/ativos", headers=h, json=ativo).status_code == 201
    assert cliente.post("/ativos", headers=h, json=ativo).status_code == 422


def test_ativo_inexistente(cliente, contas):
    assert cliente.get("/ativos/999", headers=contas["ana"]["headers"]).status_code == 404


def test_rotas_exigem_login(cliente):
    for metodo, rota in [("get", "/ativos"), ("get", "/ativos/1"), ("post", "/ativos")]:
        assert getattr(cliente, metodo)(rota).status_code == 401


def test_solicitante_nao_cadastra_ativo(cliente, contas):
    r = cliente.post(
        "/ativos",
        headers=contas["ana"]["headers"],
        json={"patrimonio": "PAT-9", "tipo": "outro", "descricao": "X", "setor": "TI"},
    )
    assert r.status_code == 403


def test_token_invalido_e_alg_none_recusados(cliente):
    falso = jwt.encode(
        {
            "sub": "1",
            "perfil": "admin",
            "iss": config.JWT_EMISSOR,
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        None,
        algorithm="none",
    )
    assert cliente.get("/ativos", headers={"Authorization": f"Bearer {falso}"}).status_code == 401
    assert cliente.get("/ativos", headers=emitir_token(1, "admin", segredo="x" * 40)).status_code == 401
    assert cliente.get("/ativos", headers=emitir_token(1, "admin", expirado=True)).status_code == 401


def test_campos_extras_e_payload_grande_recusados(cliente, contas):
    r = cliente.post(
        "/ativos",
        headers=contas["carla"]["headers"],
        json={"patrimonio": "PAT-9", "tipo": "outro", "descricao": "X", "setor": "TI", "extra": 1},
    )
    assert r.status_code == 422
    grande = '{"patrimonio": "PAT-9", "descricao": "' + ("x" * 70000) + '"}'
    r2 = cliente.post("/ativos", headers={**contas["carla"]["headers"], "Content-Type": "application/json"}, content=grande)
    assert r2.status_code == 413


def test_saude_e_cabecalhos(cliente):
    r = cliente.get("/saude", headers={"X-Request-ID": "inv_123"})
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["servico"] == "inventario"
    assert r.headers["x-request-id"] == "inv_123"
    assert r.headers["x-content-type-options"] == "nosniff"
