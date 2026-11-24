"""Popula equipamentos de exemplo quando o banco de inventário está vazio (apenas para aula)."""
from sqlalchemy.orm import Session

from app.inventario import servico as inventario
from app.inventario.esquemas import AtivoCriar


def carregar(db: Session) -> None:
    if inventario.listar(db):
        return
    for patrimonio, tipo, descricao, setor in [
        ("PAT-0001", "computador", "Desktop Dell OptiPlex", "Financeiro"),
        ("PAT-0002", "impressora", "Impressora HP LaserJet", "RH"),
        ("PAT-0003", "notebook", "Notebook Lenovo ThinkPad", "TI"),
    ]:
        inventario.criar(db, AtivoCriar(patrimonio=patrimonio, tipo=tipo, descricao=descricao, setor=setor))
