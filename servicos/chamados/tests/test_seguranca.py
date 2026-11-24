"""Testes de segurança do serviço de Chamados."""
from datetime import datetime, timedelta, timezone

import jwt

from app import config
from tests.conftest import emitir_token


def abrir(cliente, h, **extra):
    return cliente.post(
        "/chamados",
        headers=h,
        json={"titulo": "Teste", "descricao": "Teste", "prioridade": "baixa", **extra},
    )


def test_rotas_exigem_login(cliente):
    for metodo, rota in [("get", "/chamados"), ("get", "/chamados/painel"), ("get", "/chamados/1"), ("post", "/chamados")]:
        assert getattr(cliente, metodo)(rota).status_code == 401


def test_tokens_invalidos_recusados(cliente):
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
    assert cliente.get("/chamados", headers={"Authorization": f"Bearer {falso}"}).status_code == 401
    assert cliente.get("/chamados", headers=emitir_token(1, "admin", segredo="x" * 40)).status_code == 401
    assert cliente.get("/chamados", headers=emitir_token(1, "admin", expirado=True)).status_code == 401


def test_solicitante_nao_ve_chamado_de_outra_pessoa(cliente, contas):
    cid = abrir(cliente, contas["ana"]["headers"]).json()["id"]
    assert cliente.get(f"/chamados/{cid}", headers=contas["bia"]["headers"]).status_code == 404
    assert cliente.get("/chamados", headers=contas["bia"]["headers"]).json() == []


def test_solicitante_nao_atribui_nem_resolve(cliente, contas):
    cid = abrir(cliente, contas["ana"]["headers"]).json()["id"]
    h = contas["ana"]["headers"]
    assert cliente.patch(f"/chamados/{cid}/atribuir", headers=h, json={"tecnico_id": contas["carla"]["id"]}).status_code == 403
    assert cliente.patch(f"/chamados/{cid}/status", headers=h, json={"status": "em_atendimento"}).status_code == 403


def test_nao_da_para_abrir_ou_comentar_em_nome_de_outro(cliente, contas):
    assert abrir(cliente, contas["ana"]["headers"], solicitante_id=contas["bia"]["id"]).status_code == 422
    cid = abrir(cliente, contas["ana"]["headers"]).json()["id"]
    r = cliente.post(
        f"/chamados/{cid}/comentarios",
        headers=contas["ana"]["headers"],
        json={"texto": "oi", "autor_id": contas["carla"]["id"]},
    )
    assert r.status_code == 422


def test_titulo_e_requisicao_grandes_recusados(cliente, contas):
    assert abrir(cliente, contas["ana"]["headers"], titulo="x" * 500).status_code == 422
    corpo = '{"titulo": "' + "x" * 70000 + '"}'
    r = cliente.post("/chamados", headers={**contas["ana"]["headers"], "Content-Type": "application/json"}, content=corpo)
    assert r.status_code == 413


def test_texto_com_html_e_guardado_como_texto(cliente, contas):
    r = abrir(cliente, contas["ana"]["headers"], titulo="<script>alert(1)</script>")
    assert r.status_code == 201 and r.json()["titulo"] == "<script>alert(1)</script>"
