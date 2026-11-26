"""Acesso ao banco para alertas (issues #20 e #27).

Unica camada que fala SQLAlchemy quando o assunto e alerta. A tela de resolver
alertas e a issue #28.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from ..banco import sessao
from ..models import Alerta, Leitura, Medidor, StatusAlerta, TipoAlerta


def listar_abertos(id_setor: int | None = None, limite: int = 50) -> list[Alerta]:
    """Alertas ABERTOS, do mais recente para o mais antigo.

    O joinedload traz leitura, medidor e setor de uma vez: a tela mostra os tres
    em cada linha, e sem isso seriam tres consultas por alerta.
    """
    consulta = (
        select(Alerta)
        .options(joinedload(Alerta.leitura).joinedload(Leitura.medidor).joinedload(Medidor.setor))
        .join(Leitura)
        .join(Medidor)
        .where(Alerta.status == StatusAlerta.ABERTO)
        .order_by(Alerta.criado_em.desc(), Alerta.id.desc())
        .limit(limite)
    )
    if id_setor is not None:
        consulta = consulta.where(Medidor.id_setor == id_setor)
    return list(sessao().scalars(consulta))


def buscar_por_id(id_alerta: int) -> Alerta | None:
    """Um alerta, com leitura, medidor e setor ja carregados (issue #28)."""
    return sessao().scalar(
        select(Alerta)
        .options(joinedload(Alerta.leitura).joinedload(Leitura.medidor).joinedload(Medidor.setor))
        .where(Alerta.id == id_alerta)
    )


def listar(
    tipo: TipoAlerta | None = None,
    status: StatusAlerta | None = None,
    id_setor: int | None = None,
    pagina: int = 1,
    por_pagina: int = 25,
) -> tuple[list[Alerta], int]:
    """Alertas filtrados e paginados. Devolve (alertas, total). Issue #28.

    Filtro e paginacao NAO sao opcionais aqui, e e por uma razao medida: so o
    setor Producao abre ~406 alertas de fator de potencia por semana (60,4% dos
    periodos abaixo de 0,92). Sem filtro e sem pagina, a tela de resolver seria
    inutilizavel ja na primeira semana de dados.
    """
    filtros = []
    if tipo is not None:
        filtros.append(Alerta.tipo == tipo)
    if status is not None:
        filtros.append(Alerta.status == status)
    if id_setor is not None:
        filtros.append(Medidor.id_setor == id_setor)

    total = sessao().scalar(
        select(func.count()).select_from(Alerta).join(Leitura).join(Medidor).where(*filtros)
    )

    consulta = (
        select(Alerta)
        .options(joinedload(Alerta.leitura).joinedload(Leitura.medidor).joinedload(Medidor.setor))
        .options(joinedload(Alerta.usuario_resolucao))
        .join(Leitura)
        .join(Medidor)
        .where(*filtros)
        .order_by(Alerta.criado_em.desc(), Alerta.id.desc())
        .limit(por_pagina)
        .offset((pagina - 1) * por_pagina)
    )
    return list(sessao().scalars(consulta)), total


def contar_por_tipo_e_status() -> dict[tuple, int]:
    """Totais por (tipo, status). Alimenta os contadores dos filtros da #28."""
    consulta = select(Alerta.tipo, Alerta.status, func.count()).group_by(
        Alerta.tipo, Alerta.status
    )
    return {(tipo, status): total for tipo, status, total in sessao().execute(consulta)}


def salvar(alerta: Alerta) -> Alerta:
    """Grava a alteracao de um alerta ja existente (issue #28)."""
    sessao().commit()
    return alerta


def salvar_varios(alertas: list[Alerta]) -> list[Alerta]:
    """Grava os alertas de uma leitura (issue #27).

    Os dois alertas de uma mesma leitura entram num commit so: ou a leitura fica
    com os dois, ou com nenhum. Gravar um de cada vez deixaria o segundo falhar
    sozinho e a tela mostraria metade do motivo.
    """
    if not alertas:
        return []
    sessao_atual = sessao()
    sessao_atual.add_all(alertas)
    sessao_atual.commit()
    return alertas


def contar_abertos_por_tipo(id_setor: int | None = None) -> dict:
    """Quantos alertas abertos de cada tipo. Alimenta os totais do painel."""
    consulta = (
        select(Alerta.tipo, func.count())
        .select_from(Alerta)
        .join(Leitura)
        .join(Medidor)
        .where(Alerta.status == StatusAlerta.ABERTO)
        .group_by(Alerta.tipo)
    )
    if id_setor is not None:
        consulta = consulta.where(Medidor.id_setor == id_setor)
    return {tipo: total for tipo, total in sessao().execute(consulta)}
