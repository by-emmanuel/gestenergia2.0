"""Acesso ao banco para leituras (issue #18).

Unica camada que fala SQLAlchemy quando o assunto e leitura. As rotas nunca
chegam aqui direto: rota -> service -> repository.
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from ..banco import sessao
from ..models import Leitura, Medidor


def existe(id_medidor: int, data_hora: datetime) -> bool:
    """Regra 3: um medidor nao pode ter duas leituras na mesma data_hora.

    O banco garante com uq_leitura_medidor_data_hora; esta consulta existe para
    o servico recusar com mensagem clara antes de o banco reclamar.
    """
    return (
        sessao().scalar(
            select(func.count())
            .select_from(Leitura)
            .where(Leitura.id_medidor == id_medidor, Leitura.data_hora == data_hora)
        )
        > 0
    )


def ultimas_do_medidor(id_medidor: int, quantidade: int) -> list[Leitura]:
    """As N leituras mais recentes do medidor, da mais nova para a mais antiga.

    E o insumo da regra 4: a previsao precisa de 4 leituras anteriores para
    montar lag_1 a lag_4 (issue #26).
    """
    return list(
        sessao().scalars(
            select(Leitura)
            .where(Leitura.id_medidor == id_medidor)
            .order_by(Leitura.data_hora.desc())
            .limit(quantidade)
        )
    )


def anteriores_a(id_medidor: int, data_hora: datetime, quantidade: int) -> list[Leitura]:
    """As N leituras do medidor ANTERIORES a data_hora, da mais nova para a mais antiga.

    E o insumo certo da regra 4, e nao `ultimas_do_medidor`: o que monta lag_1 a
    lag_4 sao as leituras que vieram ANTES do periodo que se quer prever, nao as
    mais recentes do medidor.

    A diferenca so aparece quando a leitura nao e a mais nova de todas — que e
    exatamente o caso da importacao de CSV (#19) com o arquivo fora de ordem, e
    o de quem registra a mao uma leitura esquecida de ontem. Nesses casos
    `ultimas_do_medidor` devolveria leituras do FUTURO daquele instante como se
    fossem o passado dele, e o modelo preveria com dado que nao existia.
    """
    return list(
        sessao().scalars(
            select(Leitura)
            .where(Leitura.id_medidor == id_medidor, Leitura.data_hora < data_hora)
            .order_by(Leitura.data_hora.desc())
            .limit(quantidade)
        )
    )


def data_horas_existentes(id_medidor: int, inicio: datetime, fim: datetime) -> set[datetime]:
    """Que data_horas o medidor ja tem naquele intervalo (issue #19).

    Regra 3 aplicada a importacao: em vez de uma consulta `existe` por linha —
    35.040 consultas num ano — traz de uma vez as que ja existem na faixa do
    arquivo, e a conferencia vira uma busca em conjunto na memoria.
    """
    return set(
        sessao().scalars(
            select(Leitura.data_hora).where(
                Leitura.id_medidor == id_medidor,
                Leitura.data_hora >= inicio,
                Leitura.data_hora <= fim,
            )
        )
    )


def salvar_varias(leituras: list[Leitura]) -> list[Leitura]:
    """Grava um lote de leituras num commit so (issue #19)."""
    if not leituras:
        return []
    sessao_atual = sessao()
    sessao_atual.add_all(leituras)
    sessao_atual.commit()
    return leituras


def listar_recentes(limite: int = 50) -> list[Leitura]:
    """Ultimas leituras de todos os medidores, com medidor e setor carregados.

    O joinedload evita uma consulta por linha na tela (problema N+1).
    """
    return list(
        sessao().scalars(
            select(Leitura)
            .options(joinedload(Leitura.medidor).joinedload(Medidor.setor))
            .order_by(Leitura.data_hora.desc(), Leitura.id.desc())
            .limit(limite)
        )
    )


def contar() -> int:
    return sessao().scalar(select(func.count()).select_from(Leitura))


def salvar(leitura: Leitura) -> Leitura:
    """Grava a leitura e devolve com o id preenchido."""
    sessao_atual = sessao()
    sessao_atual.add(leitura)
    sessao_atual.commit()
    return leitura


def desfazer() -> None:
    """Devolve a sessao ao estado utilizavel depois de um erro de gravacao.

    Sem isto a sessao fica em "pending rollback" e QUALQUER operacao seguinte na
    mesma requisicao falha, mesmo que quem chamou tenha tratado o erro. Quem
    descobriu isso foi o teste da corrida de leitura duplicada.
    """
    sessao().rollback()


def serie_do_medidor(id_medidor: int, quantidade: int) -> list[Leitura]:
    """As N leituras mais recentes do medidor, em ordem CRONOLOGICA.

    E a serie do grafico do painel (issue #20). A consulta pega as mais recentes
    (ordem decrescente, com limite) e a lista e invertida no fim, porque o
    grafico precisa do tempo crescendo da esquerda para a direita.

    A janela e por CONTAGEM, nao por data: as bases sao de 2018 e 2014, entao um
    filtro "ultimos 7 dias" contado de hoje devolveria tela vazia. Contando
    leituras a partir da mais recente, a janela sempre cai onde ha dado — e com
    cadencia de 15 minutos, 96 leituras sao um dia.
    """
    recentes = sessao().scalars(
        select(Leitura)
        .where(Leitura.id_medidor == id_medidor)
        .order_by(Leitura.data_hora.desc())
        .limit(quantidade)
    )
    return list(recentes)[::-1]


def medidor_com_leitura_mais_recente(ids_de_medidor: list[int]) -> int | None:
    """Qual destes medidores tem a leitura mais recente, ou None se nenhum tem.

    O painel usa isso para abrir num medidor que tenha dado. Sem isso ele abria
    no primeiro em ordem alfabetica, que pode nao ter leitura nenhuma — grafico
    vazio com dado disponivel ao lado.
    """
    if not ids_de_medidor:
        return None
    return sessao().scalar(
        select(Leitura.id_medidor)
        .where(Leitura.id_medidor.in_(ids_de_medidor))
        .order_by(Leitura.data_hora.desc())
        .limit(1)
    )
