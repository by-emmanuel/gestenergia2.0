"""Acesso ao banco para setores (issue #16).

Unica camada que fala SQLAlchemy quando o assunto e setor. As rotas nunca chegam
aqui direto: rota -> service -> repository.
"""

from sqlalchemy import func, select

from ..banco import sessao
from ..models import Medidor, Setor


def listar(apenas_ativos: bool = False) -> list[Setor]:
    """Todos os setores, em ordem alfabetica."""
    consulta = select(Setor).order_by(Setor.nome)
    if apenas_ativos:
        consulta = consulta.where(Setor.ativo.is_(True))
    return list(sessao().scalars(consulta))


def buscar_por_id(id_setor: int) -> Setor | None:
    return sessao().get(Setor, id_setor)


def buscar_por_nome(nome: str) -> Setor | None:
    """Usado para barrar nome repetido antes de o banco reclamar.

    A colacao do MySQL (utf8mb4_0900_ai_ci) ignora maiusculas, entao "Producao"
    encontra "PRODUCAO".
    """
    return sessao().scalar(select(Setor).where(Setor.nome == nome))


def contar_medidores(id_setor: int) -> int:
    """Quantos medidores o setor tem. Serve para explicar por que nao se apaga."""
    return sessao().scalar(
        select(func.count()).select_from(Medidor).where(Medidor.id_setor == id_setor)
    )


def salvar(setor: Setor) -> Setor:
    """Grava a inclusao ou a alteracao e devolve o setor com o id preenchido."""
    sessao_atual = sessao()
    sessao_atual.add(setor)
    sessao_atual.commit()
    return setor
