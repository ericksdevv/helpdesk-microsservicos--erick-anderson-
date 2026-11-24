"""Popula chamados de exemplo de forma independente, sem exigir rede no boot."""
from datetime import datetime

from sqlalchemy.orm import Session

from app import eventos
from app.chamados import repositorio, servico
from app.chamados.modelos import Chamado


def carregar(db: Session) -> None:
    if repositorio.listar(db):
        return

    agora = datetime.now()
    # IDs de referência alinhados com os dados de exemplo de Usuários (Ana=2, Bruno=3, Carla=4) e Inventário (1, 2)
    p1 = servico.calcular_prazo("alta", agora)
    c1 = repositorio.salvar_com_outbox(
        db,
        Chamado(
            titulo="Computador não liga",
            descricao="Apertei o botão e nada acontece.",
            prioridade="alta",
            status="em_atendimento",
            solicitante_id=2,
            tecnico_id=4,
            ativo_id=1,
            criado_em=agora,
            prazo_sla=p1,
        ),
        eventos.criar_outbox("ChamadoAberto", 2, f"Seu chamado #{{chamado_id}} foi aberto. Prazo: {p1:%d/%m %H:%M}."),
    )
    db.add(eventos.criar_outbox("ChamadoAtribuido", 4, f"O chamado #{c1.id} foi atribuído a você.", chamado_id=c1.id))
    db.commit()

    p2 = servico.calcular_prazo("media", agora)
    repositorio.salvar_com_outbox(
        db,
        Chamado(
            titulo="Impressora atolando papel",
            descricao="Atola a cada 3 folhas.",
            prioridade="media",
            status="aberto",
            solicitante_id=3,
            ativo_id=2,
            criado_em=agora,
            prazo_sla=p2,
        ),
        eventos.criar_outbox("ChamadoAberto", 3, f"Seu chamado #{{chamado_id}} foi aberto. Prazo: {p2:%d/%m %H:%M}."),
    )

    p3 = servico.calcular_prazo("baixa", agora)
    repositorio.salvar_com_outbox(
        db,
        Chamado(
            titulo="Acesso ao sistema de RH",
            descricao="Preciso de acesso para a nova estagiária.",
            prioridade="baixa",
            status="aberto",
            solicitante_id=3,
            criado_em=agora,
            prazo_sla=p3,
        ),
        eventos.criar_outbox("ChamadoAberto", 3, f"Seu chamado #{{chamado_id}} foi aberto. Prazo: {p3:%d/%m %H:%M}."),
    )
    eventos.publicar_pendentes(db)
