"""Acesso ao banco para medidores (issue #17).

Unica camada que fala SQLAlchemy quando o assunto e medidor. As rotas nunca
chegam aqui direto: rota -> service -> repository.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from ..banco import sessao
from ..models import Leitura, Medidor, Setor


def listar(apenas_ativos: bool = False) -> list[Medidor]:
    """Medidores com o setor ja carregado, em ordem de codigo.

    O joinedload evita uma consulta por linha na tela (problema N+1): a lista
    mostra o nome do setor de cada medidor.
    """
    consulta = (
        select(Medidor)
        .options(joinedload(Medidor.setor))
        .join(Setor)
        .order_by(Setor.nome, Medidor.codigo)
    )
    if apenas_ativos:
        consulta = consulta.where(Medidor.ativo.is_(True))
    return list(sessao().scalars(consulta))


def listar_por_setor(id_setor: int, apenas_ativos: bool = True) -> list[Medidor]:
    """Medidores de um setor. Usado no registro de leitura (issue #18)."""
    consulta = select(Medidor).where(Medidor.id_setor == id_setor).order_by(Medidor.codigo)
    if apenas_ativos:
        consulta = consulta.where(Medidor.ativo.is_(True))
    return list(sessao().scalars(consulta))


def buscar_por_id(id_medidor: int) -> Medidor | None:
    return sessao().get(Medidor, id_medidor)


def buscar_por_codigo(codigo: str) -> Medidor | None:
    """Usado para barrar codigo repetido antes de o banco reclamar.

    A colacao do MySQL (utf8mb4_0900_ai_ci) ignora maiusculas, entao "med-prod"
    encontra "MED-PROD".
    """
    return sessao().scalar(select(Medidor).where(Medidor.codigo == codigo))


def contar_leituras(id_medidor: int) -> int:
    """Quantas leituras o medidor tem. Explica por que se desativa em vez de apagar."""
    return sessao().scalar(
        select(func.count()).select_from(Leitura).where(Leitura.id_medidor == id_medidor)
    )


def salvar(medidor: Medidor) -> Medidor:
    """Grava a inclusao ou a alteracao e devolve o medidor com o id preenchido."""
    sessao_atual = sessao()
    sessao_atual.add(medidor)
    sessao_atual.commit()
    return medidor
