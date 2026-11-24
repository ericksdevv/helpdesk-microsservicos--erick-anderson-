"""Erros de negócio do serviço de Inventário."""


class NaoEncontrado(Exception):
    pass


class RegraDeNegocio(Exception):
    pass


class SemPermissao(Exception):
    pass
