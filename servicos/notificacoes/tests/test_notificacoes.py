from datetime import datetime, timedelta, timezone

import jwt

from app import config, consumidor
from tests.conftest import emitir_token


class FakeRedisStream:
    def __init__(self, mensagens=None):
        self.mensagens = list(mensagens or [])
        self.acks = []
        self.dlq = []

    def ping(self):
        return True

    def xautoclaim(self, *_a, **_kw):
        return ("0-0", [], [])

    def xreadgroup(self, *_a, **_kw):
        if not self.mensagens:
            return []
        lote = self.mensagens[:]
        self.mensagens.clear()
        return [(config.EVENTOS_STREAM, lote)]

    def xack(self, stream, grupo, msg_id):
        self.acks.append((stream, grupo, msg_id))
        return 1

    def xadd(self, stream, campos, **_kw):
        if stream == config.EVENTOS_DLQ:
            self.dlq.append(campos)
        return "dlq-1"

    def xlen(self, stream):
        return len(self.dlq) if stream == config.EVENTOS_DLQ else len(self.mensagens)


def test_consome_eventos_e_isola_por_destinatario(sessao, cliente, contas):
    fake = FakeRedisStream(
        [
            (
                "1-0",
                {
                    "event_id": "evt-1",
                    "tipo": "ChamadoAberto",
                    "destinatario_id": "2",
                    "chamado_id": "10",
                    "mensagem": "Seu chamado #10 foi aberto.",
                },
            ),
            (
                "2-0",
                {
                    "event_id": "evt-2",
                    "tipo": "ChamadoAtribuido",
                    "destinatario_id": "4",
                    "chamado_id": "10",
                    "mensagem": "O chamado #10 foi atribuído a você.",
                },
            ),
        ]
    )
    with sessao() as db:
        qtd = consumidor.consumir_lote(fake, db, block_ms=0)
    assert qtd == 2 and len(fake.acks) == 2

    avisos_ana = cliente.get("/notificacoes", headers=contas["ana"]["headers"]).json()
    avisos_bia = cliente.get("/notificacoes", headers=contas["bia"]["headers"]).json()
    avisos_carla = cliente.get("/notificacoes", headers=contas["carla"]["headers"]).json()
    assert len(avisos_ana) == 1 and avisos_ana[0]["tipo"] == "ChamadoAberto"
    assert avisos_bia == []
    assert len(avisos_carla) == 1 and avisos_carla[0]["tipo"] == "ChamadoAtribuido"


def test_idempotencia_ignora_evento_duplicado(sessao, cliente, contas):
    evento = {
        "event_id": "evt-unico-99",
        "tipo": "ChamadoResolvido",
        "destinatario_id": "2",
        "chamado_id": "10",
        "mensagem": "Chamado resolvido.",
    }
    fake = FakeRedisStream([("10-0", evento), ("11-0", evento)])
    with sessao() as db:
        consumidor.consumir_lote(fake, db, block_ms=0)
    assert len(fake.acks) == 2
    assert len(cliente.get("/notificacoes", headers=contas["ana"]["headers"]).json()) == 1


def test_evento_invalido_vai_para_dlq(sessao):
    fake = FakeRedisStream(
        [
            (
                "99-0",
                {
                    "event_id": "evt-bad",
                    "tipo": "TipoInexistente",
                    "destinatario_id": "2",
                    "mensagem": "inválido",
                },
            )
        ]
    )
    with sessao() as db:
        consumidor.consumir_lote(fake, db, block_ms=0)
    assert len(fake.dlq) == 1 and fake.dlq[0]["motivo"] == "payload_invalido"
    assert len(fake.acks) == 1


def test_exige_login_e_valida_token(cliente):
    assert cliente.get("/notificacoes").status_code == 401
    falso = jwt.encode(
        {
            "sub": "2",
            "perfil": "solicitante",
            "iss": config.JWT_EMISSOR,
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        None,
        algorithm="none",
    )
    assert cliente.get("/notificacoes", headers={"Authorization": f"Bearer {falso}"}).status_code == 401
    assert cliente.get("/notificacoes", headers=emitir_token(2, "solicitante", expirado=True)).status_code == 401


def test_saude_notificacoes(cliente):
    r = cliente.get("/saude", headers={"X-Request-ID": "not_123"})
    assert r.status_code == 200
    assert r.json()["servico"] == "notificacoes" and r.json()["banco"] == "ok"
    assert r.headers["x-request-id"] == "not_123"
