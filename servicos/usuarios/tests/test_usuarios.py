def test_admin_cria_usuario(cliente, contas):
    r = cliente.post(
        "/usuarios",
        headers=contas["admin"]["headers"],
        json={"nome": "Davi", "email": "davi@x.com", "perfil": "tecnico", "senha": "Forte1234"},
    )
    assert r.status_code == 201
    assert "senha" not in r.json() and "senha_hash" not in r.json()


def test_email_repetido_e_recusado(cliente, contas):
    dados = {"nome": "Ana 2", "email": "ANA@x.com", "perfil": "solicitante", "senha": "Forte1234"}
    assert cliente.post("/usuarios", headers=contas["admin"]["headers"], json=dados).status_code == 422


def test_usuario_inexistente(cliente, contas):
    assert cliente.get("/usuarios/99", headers=contas["ana"]["headers"]).status_code == 404


def test_lista_publica_nao_mostra_email(cliente, contas):
    lista = cliente.get("/usuarios", headers=contas["ana"]["headers"]).json()
    assert lista and all("email" not in u for u in lista)


def test_obter_usuario_por_id_e_filtro_perfil(cliente, contas):
    tecnicos = cliente.get("/usuarios", params={"perfil": "tecnico"}, headers=contas["ana"]["headers"]).json()
    assert len(tecnicos) == 1 and tecnicos[0]["perfil"] == "tecnico"
    detalhe = cliente.get(f"/usuarios/{contas['carla']['id']}", headers=contas["ana"]["headers"])
    assert detalhe.status_code == 200 and "email" not in detalhe.json()


def test_saude_usuarios(cliente):
    r = cliente.get("/saude")
    assert r.status_code == 200
    assert r.json()["status"] == "ok" and r.json()["servico"] == "usuarios"
