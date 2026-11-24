"""Regras do serviço de Notificações com garantia de idempotência por event_id."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.notificacoes.modelos import EventoProcessado, Notificacao


def registrar_evento(
    db: Session,
    event_id: str,
    tipo: str,
    destinatario_id: int,
    mensagem: str,
    criada_em: datetime | None = None,
) -> tuple[Notificacao | None, bool]:
    """Grava a notificação se o event_id ainda não foi processado. Retorna (aviso, criado_agora)."""
    ja_processado = db.scalar(select(EventoProcessado).where(EventoProcessado.event_id == event_id))
    if ja_processado is not None:
        return None, False

    agora = criada_em or datetime.now()
    aviso = Notificacao(
        tipo=tipo,
        destinatario_id=destinatario_id,
        mensagem=mensagem[:300],
        criada_em=agora,
    )
    marca = EventoProcessado(event_id=event_id, tipo=tipo, processado_em=datetime.now())
    db.add(aviso)
    db.add(marca)
    db.commit()
    db.refresh(aviso)
    return aviso, True


def listar(db: Session, destinatario_id: int | None = None) -> list[Notificacao]:
    consulta = select(Notificacao).order_by(Notificacao.id)
    if destinatario_id is not None:
        consulta = consulta.where(Notificacao.destinatario_id == destinatario_id)
    return list(db.scalars(consulta))


def contar_processados(db: Session) -> int:
    return db.query(EventoProcessado).count()
