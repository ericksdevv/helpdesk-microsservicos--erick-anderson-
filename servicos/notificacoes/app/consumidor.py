"""Consumidor assíncrono de eventos via Redis Streams com Consumer Group, idempotência e DLQ."""
import logging
from datetime import datetime

import redis
from sqlalchemy.orm import Session

from app import config
from app.notificacoes import servico

log = logging.getLogger("helpdesk.notificacoes.consumidor")

TIPOS_PERMITIDOS = frozenset({"ChamadoAberto", "ChamadoAtribuido", "ChamadoResolvido"})
_tentativas_msg: dict[str, int] = {}
_consumidor_ativo = False


def obter_redis() -> redis.Redis | None:
    if not config.REDIS_URL:
        return None
    return redis.Redis.from_url(
        config.REDIS_URL, decode_responses=True, socket_timeout=2.0, socket_connect_timeout=1.0
    )


def garantir_grupo(cliente: redis.Redis) -> None:
    try:
        cliente.xgroup_create(config.EVENTOS_STREAM, config.EVENTOS_GRUPO, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def _enviar_dlq(cliente: redis.Redis, msg_id: str, campos: dict, motivo: str) -> None:
    payload_dlq = {
        "origem_id": msg_id,
        "motivo": motivo[:120],
        "event_id": str(campos.get("event_id", ""))[:36],
        "tipo": str(campos.get("tipo", ""))[:40],
        "destinatario_id": str(campos.get("destinatario_id", ""))[:20],
        "mensagem": str(campos.get("mensagem", ""))[:300],
    }
    cliente.xadd(config.EVENTOS_DLQ, payload_dlq, maxlen=2000, approximate=True)
    cliente.xack(config.EVENTOS_STREAM, config.EVENTOS_GRUPO, msg_id)
    _tentativas_msg.pop(msg_id, None)


def processar_mensagem(cliente: redis.Redis, db: Session, msg_id: str, campos: dict) -> str:
    """Processa um evento do Redis Stream. Retorna: processado | duplicado | dlq | falha."""
    event_id = str(campos.get("event_id") or "").strip()
    tipo = str(campos.get("tipo") or "").strip()
    mensagem = str(campos.get("mensagem") or "").strip()
    correlation_id = str(campos.get("correlation_id") or "-")
    try:
        destinatario_id = int(campos.get("destinatario_id", 0))
    except (TypeError, ValueError):
        destinatario_id = 0

    if not event_id or len(event_id) > 36 or tipo not in TIPOS_PERMITIDOS or destinatario_id <= 0 or not mensagem:
        log.warning("Evento inválido movido para DLQ msg_id=%s correlation_id=%s", msg_id, correlation_id)
        _enviar_dlq(cliente, msg_id, campos, "payload_invalido")
        return "dlq"

    criada_em = None
    if campos.get("criado_em"):
        try:
            criada_em = datetime.fromisoformat(str(campos["criado_em"]))
        except ValueError:
            criada_em = None

    try:
        _, criado_agora = servico.registrar_evento(
            db,
            event_id=event_id,
            tipo=tipo,
            destinatario_id=destinatario_id,
            mensagem=mensagem,
            criada_em=criada_em,
        )
        cliente.xack(config.EVENTOS_STREAM, config.EVENTOS_GRUPO, msg_id)
        _tentativas_msg.pop(msg_id, None)
        if criado_agora:
            log.info("Evento processado tipo=%s event_id=%s correlation_id=%s", tipo, event_id, correlation_id)
            return "processado"
        return "duplicado"
    except Exception as exc:
        db.rollback()
        tentativas = _tentativas_msg.get(msg_id, 0) + 1
        _tentativas_msg[msg_id] = tentativas
        log.warning("Erro ao processar msg_id=%s tentativa=%s: %s", msg_id, tentativas, exc)
        if tentativas >= config.MAX_TENTATIVAS_EVENTO:
            _enviar_dlq(cliente, msg_id, campos, f"erro_persistencia: {type(exc).__name__}")
            return "dlq"
        return "falha"


def consumir_lote(cliente: redis.Redis, db: Session, block_ms: int = 1000) -> int:
    """Lê mensagens pendentes (reclaim) e novas do grupo no Redis Stream."""
    processadas = 0
    try:
        reivindicadas = cliente.xautoclaim(
            config.EVENTOS_STREAM,
            config.EVENTOS_GRUPO,
            config.CONSUMIDOR_NOME,
            min_idle_time=30000,
            start_id="0-0",
            count=20,
        )
        mensagens_antigas = reivindicadas[1] if isinstance(reivindicadas, (list, tuple)) and len(reivindicadas) > 1 else []
        for msg_id, campos in mensagens_antigas:
            processar_mensagem(cliente, db, msg_id, campos)
            processadas += 1
    except (redis.ResponseError, AttributeError):
        pass

    novas = cliente.xreadgroup(
        config.EVENTOS_GRUPO,
        config.CONSUMIDOR_NOME,
        streams={config.EVENTOS_STREAM: ">"},
        count=20,
        block=block_ms,
    )
    for _stream, entradas in novas or []:
        for msg_id, campos in entradas:
            processar_mensagem(cliente, db, msg_id, campos)
            processadas += 1
    return processadas


def definir_ativo(ativo: bool) -> None:
    global _consumidor_ativo
    _consumidor_ativo = ativo


def status_consumidor(cliente: redis.Redis | None = None) -> dict[str, object]:
    if not config.REDIS_URL:
        return {"consumidor": "desabilitado", "dlq_pendentes": 0}
    c = cliente or obter_redis()
    try:
        c.ping()
        dlq_len = c.xlen(config.EVENTOS_DLQ)
        return {"consumidor": "ativo" if _consumidor_ativo else "conectado", "dlq_pendentes": dlq_len}
    except Exception:
        return {"consumidor": "degradado", "dlq_pendentes": 0}
