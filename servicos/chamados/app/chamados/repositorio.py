"""Acesso a dados do serviço de Chamados."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chamados.modelos import Chamado, Comentario, OutboxEvento


def salvar(db: Session, chamado: Chamado) -> Chamado:
    db.add(chamado)
    db.commit()
    db.refresh(chamado)
    return chamado


def salvar_com_outbox(db: Session, chamado: Chamado, evento: OutboxEvento | None = None) -> Chamado:
    """Persiste o chamado e o evento Outbox na mesma transação local."""
    db.add(chamado)
    if evento is not None:
        db.flush()
        evento.chamado_id = chamado.id
        evento.mensagem = evento.mensagem.format(chamado_id=chamado.id)
        db.add(evento)
    db.commit()
    db.refresh(chamado)
    return chamado


def salvar_comentario(db: Session, comentario: Comentario) -> Comentario:
    db.add(comentario)
    db.commit()
    db.refresh(comentario)
    return comentario


def buscar_por_id(db: Session, chamado_id: int) -> Chamado | None:
    return db.get(Chamado, chamado_id)


def listar(
    db: Session,
    status: str | None = None,
    tecnico_id: int | None = None,
    solicitante_id: int | None = None,
) -> list[Chamado]:
    consulta = select(Chamado).order_by(Chamado.id)
    if solicitante_id:
        consulta = consulta.where(Chamado.solicitante_id == solicitante_id)
    if status:
        consulta = consulta.where(Chamado.status == status)
    if tecnico_id:
        consulta = consulta.where(Chamado.tecnico_id == tecnico_id)
    return list(db.scalars(consulta))
