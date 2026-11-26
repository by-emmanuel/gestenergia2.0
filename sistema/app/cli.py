"""Comandos de linha de comando da aplicacao (issue #49).

    flask --app app carregar-demonstracao --limpar

Carrega os dados que a apresentacao usa: um trecho real de cada setor, com as
datas dos tres setores novos DESLOCADAS para cairem no mesmo periodo da
siderurgica.

POR QUE DESLOCAR. A base da siderurgica e de 2018 e as tres da
ElectricityLoadDiagrams sao de 2014. Com cada setor no seu ano, o painel nunca
mostra os 4 no mesmo periodo e a demonstracao fica sem gracaa.

POR QUE EM MULTIPLO DE 7 DIAS. `dia_semana` e `fim_de_semana` sao atributos do
modelo. Deslocar 1.461 dias (a distancia real entre 01/01/2014 e 01/01/2018)
jogaria uma quarta-feira para uma segunda, e o modelo passaria a receber um dia
da semana que nao corresponde ao comportamento daquela medicao. Multiplo de 7
preserva o dia da semana de cada linha.

SO NOS DADOS DA DEMONSTRACAO, NUNCA NOS DE TREINO. Os CSVs de data/setores/
ficam intactos, com as datas originais, e os modelos de ml/ foram treinados
neles. O deslocamento acontece em memoria, na hora de carregar o banco. Misturar
as duas coisas seria vazamento disfarcado.

O carregamento passa pelo MESMO caminho da tela de importacao (#19), entao gera
previsao e abre alerta exatamente como a aplicacao faz em uso normal.
"""

import csv
import io
from datetime import datetime, timedelta
from pathlib import Path

import click
from flask import current_app
from flask.cli import with_appcontext

from .banco import sessao
from .models import Alerta, Leitura
from .services import importacao_service, medidor_service

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_STEEL = RAIZ / "data" / "bruto" / "Steel_industry_data.csv"
PASTA_SETORES = RAIZ / "data" / "setores"
PERIODOS_POR_DIA = 96
DIAS_DA_SEMANA = 7

# O setor da siderurgica e a referencia de periodo; os outros tres sao
# deslocados ate ele. O nome e o do banco.sql.
SETOR_DE_REFERENCIA = "Producao"
SETORES_DESLOCADOS = {
    "Administrativo": PASTA_SETORES / "administrativo.csv",
    "Utilidades": PASTA_SETORES / "utilidades.csv",
    "Manutencao": PASTA_SETORES / "manutencao.csv",
}


def _ler_steel(semanas: int) -> tuple[str, datetime]:
    """O trecho da siderurgica, no formato original, e o seu primeiro instante.

    A siderurgica NAO esta em ordem cronologica (a linha das 00:00 vem no fim de
    cada dia), entao ordenar aqui e obrigatorio: sem isso o "primeiro instante" e
    o recorte sairiam errados.
    """
    with open(ARQUIVO_STEEL, encoding="utf-8-sig", newline="") as arquivo:
        leitor = csv.reader(arquivo)
        cabecalho = next(leitor)
        linhas = list(leitor)

    linhas.sort(key=lambda linha: datetime.strptime(linha[0], "%d/%m/%Y %H:%M"))
    recorte = linhas[: semanas * DIAS_DA_SEMANA * PERIODOS_POR_DIA]

    saida = io.StringIO()
    escritor = csv.writer(saida)
    escritor.writerow(cabecalho)
    escritor.writerows(recorte)
    return saida.getvalue(), datetime.strptime(recorte[0][0], "%d/%m/%Y %H:%M")


def _deslocamento(inicio_do_setor: datetime, inicio_da_referencia: datetime) -> timedelta:
    """O menor multiplo de 7 dias que leva o setor para dentro do periodo da referencia.

    Arredonda para CIMA para a serie deslocada comecar em cima ou depois do
    inicio da siderurgica, nunca antes — senao o painel mostraria os setores
    novos comecando num periodo em que a Producao ainda nao tem leitura.
    """
    dias = (inicio_da_referencia - inicio_do_setor).days
    semanas = -(-dias // DIAS_DA_SEMANA)  # divisao para cima
    return timedelta(days=semanas * DIAS_DA_SEMANA)


def _ler_setor(caminho: Path, semanas: int, deslocamento: timedelta | None) -> tuple[str, datetime]:
    """O trecho de um setor, com as datas deslocadas, e o seu primeiro instante.

    Quando `deslocamento` e None, so devolve o primeiro instante original — e o
    que permite calcular o deslocamento antes de aplica-lo.
    """
    with open(caminho, encoding="utf-8", newline="") as arquivo:
        leitor = csv.reader(arquivo)
        cabecalho = next(leitor)
        linhas = list(leitor)

    recorte = linhas[: semanas * DIAS_DA_SEMANA * PERIODOS_POR_DIA]
    primeiro = datetime.strptime(recorte[0][0], "%Y-%m-%d %H:%M:%S")
    if deslocamento is None:
        return "", primeiro

    saida = io.StringIO()
    escritor = csv.writer(saida)
    escritor.writerow(cabecalho)
    for linha in recorte:
        quando = datetime.strptime(linha[0], "%Y-%m-%d %H:%M:%S") + deslocamento
        escritor.writerow([quando.strftime("%Y-%m-%d %H:%M:%S"), linha[1]])
    return saida.getvalue(), primeiro + deslocamento


def _limpar() -> tuple[int, int]:
    """Apaga leituras e alertas. Os setores, medidores e usuarios ficam."""
    sessao_atual = sessao()
    alertas = sessao_atual.query(Alerta).delete()
    leituras = sessao_atual.query(Leitura).delete()
    sessao_atual.commit()
    return leituras, alertas


@click.command("carregar-demonstracao")
@click.option("--semanas", default=4, show_default=True,
              help="Quantas semanas de cada setor carregar.")
@click.option("--limpar", is_flag=True,
              help="Apaga as leituras e os alertas existentes antes de carregar.")
@with_appcontext
def carregar_demonstracao(semanas: int, limpar: bool) -> None:
    """Carrega os dados da apresentacao, com as datas dos 4 setores alinhadas."""
    for arquivo in (ARQUIVO_STEEL, *SETORES_DESLOCADOS.values()):
        if not arquivo.exists():
            raise click.ClickException(
                f"{arquivo.relative_to(RAIZ)} nao existe. Os CSVs dos setores saem de "
                "notebooks/setores_kmeans.py (issue #44)."
            )

    if limpar:
        leituras, alertas = _limpar()
        click.echo(f"apagadas {leituras:,} leituras e {alertas:,} alertas".replace(",", "."))

    medidores = {m.setor.nome: m for m in medidor_service.listar(apenas_ativos=True)}
    faltando = {SETOR_DE_REFERENCIA, *SETORES_DESLOCADOS} - set(medidores)
    if faltando:
        raise click.ClickException(
            f"sem medidor ativo para: {', '.join(sorted(faltando))}. "
            "Aplique o banco.sql antes de carregar a demonstracao."
        )

    conteudo_steel, inicio_da_referencia = _ler_steel(semanas)

    click.echo(f"\nreferencia: {SETOR_DE_REFERENCIA} comeca em "
               f"{inicio_da_referencia.strftime('%d/%m/%Y')} "
               f"({_dia_da_semana(inicio_da_referencia)})")

    cargas = [(SETOR_DE_REFERENCIA, conteudo_steel, None)]
    for nome, caminho in SETORES_DESLOCADOS.items():
        _, original = _ler_setor(caminho, semanas, None)
        deslocamento = _deslocamento(original, inicio_da_referencia)
        conteudo, novo_inicio = _ler_setor(caminho, semanas, deslocamento)

        # O multiplo de 7 so vale se o dia da semana nao mudar. Conferir e
        # barato e o erro seria silencioso: o modelo receberia um dia da semana
        # que nao corresponde ao comportamento daquela medicao.
        if original.weekday() != novo_inicio.weekday():
            raise click.ClickException(
                f"{nome}: o deslocamento mudou o dia da semana "
                f"({_dia_da_semana(original)} -> {_dia_da_semana(novo_inicio)})"
            )

        click.echo(f"  {nome:<16} {original.strftime('%d/%m/%Y')} -> "
                   f"{novo_inicio.strftime('%d/%m/%Y')}  "
                   f"(+{deslocamento.days} dias = {deslocamento.days // 7} semanas, "
                   f"{_dia_da_semana(novo_inicio)} nos dois)")
        cargas.append((nome, conteudo, deslocamento))

    click.echo("")
    total_leituras = total_alertas = 0
    for nome, conteudo, _ in cargas:
        resultado = importacao_service.importar(medidores[nome], conteudo)
        if resultado.erros:
            raise click.ClickException(f"{nome}: {'; '.join(resultado.erros)}")
        total_leituras += resultado.importadas
        total_alertas += resultado.alertas
        por_semana = resultado.alertas / semanas
        click.echo(
            f"  {nome:<16} {resultado.importadas:>6,} leituras, "
            f"{resultado.com_previsao:>6,} com previsao, "
            f"{resultado.alertas:>5,} alertas ({por_semana:.1f}/semana)  "
            f"{resultado.primeira.strftime('%d/%m')} a {resultado.ultima.strftime('%d/%m/%Y')}"
            .replace(",", ".")
        )

    click.echo(f"\n{total_leituras:,} leituras e {total_alertas:,} alertas em "
               f"{semanas} semanas dos 4 setores.".replace(",", "."))
    click.echo(f"banco: {current_app.config['NOME_DO_BANCO']}")


def _dia_da_semana(quando: datetime) -> str:
    return ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"][quando.weekday()]
