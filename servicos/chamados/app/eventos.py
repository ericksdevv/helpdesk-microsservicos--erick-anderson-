"""Publicador de eventos via Transactional Outbox + Redis Streams."""
import logging
import uuid
from datetime import datetime

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.chamados.modelos import OutboxEvento
from app.seguranca_http import request_id_ctx

log = logging.getLogger("helpdesk.chamados.eventos")

_cliente_redis: redis.Redis | None = None
_redis_url_atual = ""


def obter_redis() -> redis.Redis | None:
    global _cliente_redis, _redis_url_atual
    url = config.REDIS_URL
    if not url:
        return None
    if _cliente_redis is None or _redis_url_atual != url:
        _cliente_redis = redis.Redis.from_url(
            url, decode_responses=True, socket_timeout=1.0, socket_connect_timeout=1.0
        )
        _redis_url_atual = url
    return _cliente_redis


def criar_outbox(tipo: str, destinatario_id: int, mensagem: str, chamado_id: int = 0) -> OutboxEvento:
    return OutboxEvento(
        event_id=str(uuid.uuid4()),
        tipo=tipo,
        destinatario_id=destinatario_id,
        chamado_id=chamado_id,
        mensagem=mensagem[:300],
        correlation_id=request_id_ctx.get(),
        criado_em=datetime.now(),
    )


def publicar_pendentes(db: Session, limite: int = 50) -> int:
    """Publica eventos pendentes da Outbox para o Redis Stream. Nunca falha a operação do chamado."""
    cliente = obter_redis()
    if cliente is None:
        return 0

    pendentes = list(
        db.scalars(
            select(OutboxEvento)
            .where(OutboxEvento.publicado_em.is_(None))
            .order_by(OutboxEvento.id)
            .limit(limite)
        )
    )
    if not pendentes:
        return 0

    publicados = 0
    for ev in pendentes:
        payload = {
            "event_id": ev.event_id,
            "tipo": ev.tipo,
            "destinatario_id": str(ev.destinatario_id),
            "chamado_id": str(ev.chamado_id),
            "mensagem": ev.mensagem,
            "correlation_id": ev.correlation_id,
            "criado_em": ev.criado_em.isoformat(),
        }
        try:
            cliente.xadd(config.EVENTOS_STREAM, payload, maxlen=10000, approximate=True)
            ev.publicado_em = datetime.now()
            ev.ultimo_erro = None
            publicados += 1
        except redis.RedisError as exc:
            ev.tentativas += 1
            ev.ultimo_erro = str(exc)[:280]
            log.warning(
                "Falha ao publicar evento event_id=%s tipo=%s na fila (tentativa=%s): %s",
                ev.event_id, ev.tipo, ev.tentativas, exc,
            )
            break

    db.commit()
    return publicados


def status_fila(db: Session) -> dict[str, object]:
    pendentes = db.query(OutboxEvento).filter(OutboxEvento.publicado_em.is_(None)).count()
    cliente = obter_redis()
    if cliente is None:
        return {"fila": "desabilitada", "outbox_pendentes": pendentes}
    try:
        cliente.ping()
        return {"fila": "redis", "outbox_pendentes": pendentes}
    except redis.RedisError:
        return {"fila": "degradada", "outbox_pendentes": pendentes}
