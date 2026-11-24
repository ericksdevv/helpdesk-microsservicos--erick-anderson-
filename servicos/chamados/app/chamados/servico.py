"""Regras do serviço de Chamados.

Comunicação síncrona via HTTP (com timeout e circuit breaker) para validar ativos e técnicos,
e comunicação assíncrona via Transactional Outbox -> Redis Streams para notificar eventos.
"""
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app import clientes, eventos
from app.auth.tokens import UsuarioAutenticado
from app.chamados import repositorio
from app.chamados.esquemas import ChamadoCriar, ComentarioCriar
from app.chamados.modelos import Chamado, Comentario
from app.erros import NaoEncontrado, RegraDeNegocio, SemPermissao

HORAS_SLA = {"critica": 4, "alta": 8, "media": 24, "baixa": 72}

TRANSICOES = {
    "aberto": {"em_atendimento"},
    "em_atendimento": {"resolvido"},
    "resolvido": {"fechado", "em_atendimento"},
    "fechado": set(),
}

EQUIPE = ("tecnico", "admin")


def eh_equipe(usuario: UsuarioAutenticado) -> bool:
    return usuario.perfil in EQUIPE


def calcular_prazo(prioridade: str, inicio: datetime) -> datetime:
    return inicio + timedelta(hours=HORAS_SLA[prioridade])


def abrir(db: Session, dados: ChamadoCriar, usuario: UsuarioAutenticado) -> Chamado:
    if dados.ativo_id is not None:
        clientes.verificar_ativo(dados.ativo_id, usuario.token_bruto)

    agora = datetime.now()
    prazo = calcular_prazo(dados.prioridade, agora)
    chamado = Chamado(
        **dados.model_dump(),
        solicitante_id=usuario.id,
        status="aberto",
        criado_em=agora,
        prazo_sla=prazo,
    )
    evento = eventos.criar_outbox(
        tipo="ChamadoAberto",
        destinatario_id=usuario.id,
        mensagem=f"Seu chamado #{{chamado_id}} foi aberto. Prazo: {prazo:%d/%m %H:%M}.",
    )
    salvo = repositorio.salvar_com_outbox(db, chamado, evento)
    eventos.publicar_pendentes(db)
    return salvo


def obter(db: Session, chamado_id: int, usuario: UsuarioAutenticado) -> Chamado:
    chamado = repositorio.buscar_por_id(db, chamado_id)
    if chamado is None or not (eh_equipe(usuario) or chamado.solicitante_id == usuario.id):
        raise NaoEncontrado(f"Chamado {chamado_id} não encontrado.")
    return chamado


def listar(
    db: Session,
    usuario: UsuarioAutenticado,
    status: str | None = None,
    tecnico_id: int | None = None,
) -> list[Chamado]:
    solicitante_id = None if eh_equipe(usuario) else usuario.id
    return repositorio.listar(db, status, tecnico_id, solicitante_id)


def atribuir(db: Session, chamado_id: int, tecnico_id: int, usuario: UsuarioAutenticado) -> Chamado:
    if not eh_equipe(usuario):
        raise SemPermissao("Só técnicos e administradores atribuem chamados.")
    chamado = obter(db, chamado_id, usuario)
    if chamado.status in ("resolvido", "fechado"):
        raise RegraDeNegocio("Não é possível atribuir um chamado resolvido ou fechado.")

    tecnico = clientes.obter_tecnico(tecnico_id, usuario.token_bruto)
    chamado.tecnico_id = int(tecnico["id"])
    if chamado.status == "aberto":
        chamado.status = "em_atendimento"

    evento = eventos.criar_outbox(
        tipo="ChamadoAtribuido",
        destinatario_id=chamado.tecnico_id,
        chamado_id=chamado.id,
        mensagem="O chamado #{chamado_id} foi atribuído a você.",
    )
    salvo = repositorio.salvar_com_outbox(db, chamado, evento)
    eventos.publicar_pendentes(db)
    return salvo


def mudar_status(db: Session, chamado_id: int, novo_status: str, usuario: UsuarioAutenticado) -> Chamado:
    chamado = obter(db, chamado_id, usuario)
    pode_solicitante = chamado.status == "resolvido" and novo_status in ("fechado", "em_atendimento")
    if not (eh_equipe(usuario) or pode_solicitante):
        raise SemPermissao("Você não pode mudar o status deste chamado.")
    if novo_status not in TRANSICOES[chamado.status]:
        raise RegraDeNegocio(f"Não é possível ir de '{chamado.status}' para '{novo_status}'.")
    if novo_status == "em_atendimento" and chamado.tecnico_id is None:
        raise RegraDeNegocio("Atribua um técnico antes de iniciar o atendimento.")

    chamado.status = novo_status
    evento = None
    if novo_status == "resolvido":
        evento = eventos.criar_outbox(
            tipo="ChamadoResolvido",
            destinatario_id=chamado.solicitante_id,
            chamado_id=chamado.id,
            mensagem="Seu chamado #{chamado_id} foi resolvido. Confirme se está tudo certo.",
        )

    salvo = repositorio.salvar_com_outbox(db, chamado, evento)
    if evento is not None:
        eventos.publicar_pendentes(db)
    return salvo


def comentar(db: Session, chamado_id: int, dados: ComentarioCriar, usuario: UsuarioAutenticado) -> Comentario:
    chamado = obter(db, chamado_id, usuario)
    if chamado.status == "fechado":
        raise RegraDeNegocio("Chamados fechados não recebem comentários.")
    return repositorio.salvar_comentario(
        db,
        Comentario(chamado_id=chamado.id, autor_id=usuario.id, texto=dados.texto, criado_em=datetime.now()),
    )


def painel(db: Session, usuario: UsuarioAutenticado) -> dict:
    chamados = listar(db, usuario)
    agora = datetime.now()
    atrasados = sum(1 for c in chamados if c.status in ("aberto", "em_atendimento") and c.prazo_sla < agora)
    return {"total": len(chamados), "por_status": dict(Counter(c.status for c in chamados)), "atrasados": atrasados}
