from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Chamado(Base):
    __tablename__ = "chamados"

    id: Mapped[int] = mapped_column(primary_key=True)
    titulo: Mapped[str] = mapped_column(String(120))
    descricao: Mapped[str] = mapped_column(Text)
    prioridade: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="aberto")
    # Em microsserviços, não há chave estrangeira para outros bancos: guardamos apenas o ID de referência.
    solicitante_id: Mapped[int] = mapped_column(Integer)
    tecnico_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ativo_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime)
    prazo_sla: Mapped[datetime] = mapped_column(DateTime)

    comentarios: Mapped[list["Comentario"]] = relationship(
        back_populates="chamado", order_by="Comentario.id", cascade="all, delete-orphan"
    )


class Comentario(Base):
    __tablename__ = "comentarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    chamado_id: Mapped[int] = mapped_column(ForeignKey("chamados.id"))
    autor_id: Mapped[int] = mapped_column(Integer)
    texto: Mapped[str] = mapped_column(Text)
    criado_em: Mapped[datetime] = mapped_column(DateTime)

    chamado: Mapped[Chamado] = relationship(back_populates="comentarios")


class OutboxEvento(Base):
    """Padrão Outbox: garante envio de eventos sem perder consistência com o banco local."""

    __tablename__ = "outbox_eventos"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    tipo: Mapped[str] = mapped_column(String(40))
    destinatario_id: Mapped[int] = mapped_column(Integer)
    chamado_id: Mapped[int] = mapped_column(Integer)
    mensagem: Mapped[str] = mapped_column(String(300))
    correlation_id: Mapped[str] = mapped_column(String(64), default="-")
    criado_em: Mapped[datetime] = mapped_column(DateTime)
    publicado_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    tentativas: Mapped[int] = mapped_column(Integer, default=0)
    ultimo_erro: Mapped[str | None] = mapped_column(String(300), nullable=True)
