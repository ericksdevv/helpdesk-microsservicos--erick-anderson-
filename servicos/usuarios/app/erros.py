"""Erros de negócio do serviço de Usuários."""


class NaoEncontrado(Exception):
    """O recurso pedido não existe."""


class RegraDeNegocio(Exception):
    """A operação viola uma regra do sistema."""


class SemPermissao(Exception):
    """O usuário está autenticado, mas não pode fazer esta operação."""
