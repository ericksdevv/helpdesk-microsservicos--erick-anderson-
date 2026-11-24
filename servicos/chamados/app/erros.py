"""Erros de negócio e integração do serviço de Chamados."""


class NaoEncontrado(Exception):
    pass


class RegraDeNegocio(Exception):
    pass


class SemPermissao(Exception):
    pass


class ServicoIndisponivel(Exception):
    """Dependência externa (Usuários ou Inventário) fora do ar ou com timeout."""


class NaoAutenticado(Exception):
    """Token rejeitado pelo serviço consultado."""
