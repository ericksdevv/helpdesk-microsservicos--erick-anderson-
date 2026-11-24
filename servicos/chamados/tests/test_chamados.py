from datetime import datetime

import httpx
import redis

from app import clientes, config, eventos
from app.chamados.modelos import OutboxEvento


def abrir(cliente, contas, quem="ana", prioridade="alta", ativo_id=1, **extra):
    dados = {"titulo": "PC não liga", "descricao": "Nada acontece", "prioridade": prioridade, "ativo_id": ativo_id, **extra}
    return cliente.post("/chamados", headers=contas[quem]["headers"], json=dados)


def test_abrir_calcula_sla_repassa_token_e_publica_evento(cliente, contas, fake_redis, mock_servicos):
    r = cliente.post(
        "/chamados",
        headers={**contas["ana"]["headers"], "X-Request-ID": "trace_abc_1"},
        json={"titulo": "PC não liga", "descricao": "Nada acontece", "prioridade": "critica", "ativo_id": 1},
    )
    assert r.status_code == 201
    c = r.json()
    assert c["solicitante_id"] == contas["ana"]["id"]
    horas = (datetime.fromisoformat(c["prazo_sla"]) - datetime.fromisoformat(c["criado_em"])).total_seconds() / 3600
    assert round(horas) == 4
    # Confere repasse de Authorization e X-Request-ID para o Inventário
    assert mock_servicos["headers_recebidos"][0]["authorization"] == contas["ana"]["headers"]["Authorization"]
    assert mock_servicos["headers_recebidos"][0]["x-request-id"] == "trace_abc_1"
    # Confere evento publicado na fila
    assert len(fake_redis) == 1
    assert fake_redis[0][1]["tipo"] == "ChamadoAberto"
    assert fake_redis[0][1]["correlation_id"] == "trace_abc_1"


def test_abrir_com_ativo_inexistente(cliente, contas):
    assert abrir(cliente, contas, ativo_id=999).status_code == 404


def test_atribuir_muda_status_e_publica_evento(cliente, contas, fake_redis):
    cid = abrir(cliente, contas).json()["id"]
    r = cliente.patch(
        f"/chamados/{cid}/atribuir",
        headers=contas["carla"]["headers"],
        json={"tecnico_id": contas["carla"]["id"]},
    )
    assert r.status_code == 200 and r.json()["status"] == "em_atendimento"
    tipos = [ev[1]["tipo"] for ev in fake_redis]
    assert tipos == ["ChamadoAberto", "ChamadoAtribuido"]


def test_so_tecnico_pode_ser_atribuido(cliente, contas):
    cid = abrir(cliente, contas).json()["id"]
    r = cliente.patch(
        f"/chamados/{cid}/atribuir",
        headers=contas["carla"]["headers"],
        json={"tecnico_id": contas["ana"]["id"]},
    )
    assert r.status_code == 422


def test_fluxo_completo_de_status(cliente, contas, fake_redis):
    cid = abrir(cliente, contas).json()["id"]
    tec = contas["carla"]["headers"]
    cliente.patch(f"/chamados/{cid}/atribuir", headers=tec, json={"tecnico_id": contas["carla"]["id"]})
    assert cliente.patch(f"/chamados/{cid}/status", headers=tec, json={"status": "resolvido"}).status_code == 200
    r = cliente.patch(f"/chamados/{cid}/status", headers=contas["ana"]["headers"], json={"status": "fechado"})
    assert r.json()["status"] == "fechado"
    assert [ev[1]["tipo"] for ev in fake_redis] == ["ChamadoAberto", "ChamadoAtribuido", "ChamadoResolvido"]


def test_transicao_invalida_e_sem_tecnico(cliente, contas):
    cid = abrir(cliente, contas).json()["id"]
    assert cliente.patch(f"/chamados/{cid}/status", headers=contas["carla"]["headers"], json={"status": "fechado"}).status_code == 422
    assert cliente.patch(f"/chamados/{cid}/status", headers=contas["carla"]["headers"], json={"status": "em_atendimento"}).status_code == 422


def test_comentar_usa_usuario_logado_e_painel(cliente, contas):
    cid = abrir(cliente, contas).json()["id"]
    r = cliente.post(f"/chamados/{cid}/comentarios", headers=contas["carla"]["headers"], json={"texto": "Verificando."})
    assert r.status_code == 201 and r.json()["autor_id"] == contas["carla"]["id"]
    abrir(cliente, contas, prioridade="baixa", ativo_id=None)
    p = cliente.get("/chamados/painel", headers=contas["carla"]["headers"]).json()
    assert p["total"] == 2 and p["por_status"] == {"aberto": 2}


def test_inventario_fora_do_ar_retorna_503_e_ativa_circuit_breaker(monkeypatch, cliente, contas):
    chamadas = {"n": 0}

    def falha(_request: httpx.Request) -> httpx.Response:
        chamadas["n"] += 1
        raise httpx.ReadTimeout("timeout simulado")

    monkeypatch.setattr(clientes, "obter_cliente_http", lambda: httpx.Client(transport=httpx.MockTransport(falha)))
    monkeypatch.setattr(config, "CIRCUIT_BREAKER_LIMITE_FALHAS", 2)
    clientes.breaker_inventario.resetar()

    r1 = abrir(cliente, contas, ativo_id=1)
    r2 = abrir(cliente, contas, ativo_id=1)
    assert r1.status_code == 503 and "Inventário" in r1.json()["detail"]
    assert r2.status_code == 503
    assert clientes.breaker_inventario.estado_atual() == "open"

    # Com circuito aberto, não tenta bater na rede até passar o cooldown
    chamadas_antes = chamadas["n"]
    r3 = abrir(cliente, contas, ativo_id=1)
    assert r3.status_code == 503 and "circuito aberto" in r3.json()["detail"]
    assert chamadas["n"] == chamadas_antes


def test_usuarios_fora_do_ar_retorna_503_ao_atribuir(monkeypatch, cliente, contas):
    cid = abrir(cliente, contas, ativo_id=None).json()["id"]

    def falha_conn(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(clientes, "obter_cliente_http", lambda: httpx.Client(transport=httpx.MockTransport(falha_conn)))
    clientes.breaker_usuarios.resetar()

    r = cliente.patch(
        f"/chamados/{cid}/atribuir",
        headers=contas["carla"]["headers"],
        json={"tecnico_id": contas["carla"]["id"]},
    )
    assert r.status_code == 503 and "Usuários" in r.json()["detail"]


def test_redis_fora_do_ar_nao_impede_abertura_e_preserva_outbox(monkeypatch, sessao, cliente, contas):
    class RedisOffline:
        def ping(self):
            raise redis.RedisError("down")

        def xadd(self, *_a, **_kw):
            raise redis.RedisError("down")

    monkeypatch.setattr(eventos, "obter_redis", lambda: RedisOffline())
    r = abrir(cliente, contas, ativo_id=None)
    assert r.status_code == 201

    with sessao() as db:
        pendentes = db.query(OutboxEvento).filter(OutboxEvento.publicado_em.is_(None)).all()
        assert len(pendentes) == 1
        assert pendentes[0].tipo == "ChamadoAberto" and pendentes[0].tentativas == 1


def test_saude_chamados(cliente):
    r = cliente.get("/saude")
    assert r.status_code == 200
    dados = r.json()
    assert dados["servico"] == "chamados" and dados["dependencias"]["inventario"]["circuito"] == "closed"
