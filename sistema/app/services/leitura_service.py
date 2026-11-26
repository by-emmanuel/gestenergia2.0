"""Regras de negocio das leituras (issue #18).

Todas as validacoes moram aqui, nunca na rota e nunca no template. A importacao
de CSV (issue #19) usa ESTE servico em laco, para as regras nao existirem em
dois lugares.

As regras que esta camada garante:

  - **regra 3**: um medidor nao pode ter duas leituras com a mesma data_hora.
    Validado aqui E garantido por uq_leitura_medidor_data_hora no banco. Os dois
    sao necessarios: a validacao da a mensagem clara, e a chave unica fecha a
    corrida entre dois envios simultaneos, que a validacao sozinha perderia.
  - **regra 6**: o fator de potencia e guardado de 0 a 1, nunca em percentual.
  - consumo nunca negativo (ck_leitura_consumo_nao_negativo).

Desde a issue #27, registrar uma leitura tambem PREVE o consumo daquele periodo
(#26) e abre os alertas que a previsao e o fator de potencia dispararem. O que
nao da para prever continua indo para o banco com consumo_previsto_kwh NULL, que
a tela mostra como "sem previsao ainda" — o caminho que a regra 4 descreve.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.exc import IntegrityError

from ..models import Leitura
from ..repositories import leitura_repository, medidor_repository
from . import alerta_service, previsao_service

# Regra 1: a regra do fator de potencia mora no alerta_service, que e quem a usa
# para abrir alerta. Fica reexportada aqui porque o painel e as telas de leitura
# ja a chamavam por este modulo — e porque o lugar natural de procurar "o que
# conta como fator baixo" continua sendo o servico de leituras.
from .alerta_service import FATOR_POTENCIA_MINIMO, fator_abaixo_do_minimo  # noqa: F401

# Regra 4: a previsao precisa de 4 leituras anteriores do mesmo medidor.
LEITURAS_NECESSARIAS_PARA_PREVER = previsao_service.LEITURAS_NECESSARIAS

MENSAGEM_DUPLICADA = (
    "Este medidor já tem uma leitura registrada em {quando}. "
    "Cada medidor aceita uma única leitura por data e hora."
)


def listar_recentes(limite: int = 50) -> list[Leitura]:
    return leitura_repository.listar_recentes(limite=limite)


def contar() -> int:
    return leitura_repository.contar()


def tem_leituras_para_prever(id_medidor: int) -> bool:
    """Regra 4: diz se o medidor ja tem as 4 leituras anteriores necessarias."""
    anteriores = leitura_repository.ultimas_do_medidor(
        id_medidor, LEITURAS_NECESSARIAS_PARA_PREVER
    )
    return len(anteriores) >= LEITURAS_NECESSARIAS_PARA_PREVER


def converter_data_hora(bruto: str | None) -> tuple[datetime | None, str | None]:
    """Le a data e hora do formulario. Devolve (valor, erro).

    Aceita o que o campo datetime-local envia (2018-01-01T00:15) e a mesma coisa
    com espaco. Os microssegundos sao zerados: a coluna e DATETIME sem fracao de
    segundo, e sem zerar a comparacao da regra 3 poderia nao casar.
    """
    texto = (bruto or "").strip()
    if not texto:
        return None, "Informe a data e a hora da leitura."

    for formato in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(texto, formato).replace(microsecond=0), None
        except ValueError:
            continue
    return None, "Data e hora inválidas. Use o formato 2018-01-01 00:15."


def converter_consumo(bruto: str | None) -> tuple[Decimal | None, str | None]:
    """Le o consumo em kWh. Obrigatorio e nunca negativo."""
    texto = (bruto or "").strip().replace(" ", "")
    if not texto:
        return None, "Informe o consumo em kWh."
    try:
        valor = Decimal(texto.replace(",", "."))
    except InvalidOperation:
        return None, "O consumo precisa ser um número (ex.: 3,17)."
    if valor < 0:
        return None, "O consumo não pode ser negativo."
    return valor, None


def converter_fator_potencia(bruto: str | None) -> tuple[Decimal | None, str | None]:
    """Le o fator de potencia. Devolve (valor, erro).

    Regra 1: vazio e valido e vira NULL — hoje so o setor Producao tem esse dado,
    e leitura sem ele nao gera alerta e nao da erro.

    Regra 6: aqui o valor e de 0 a 1. Na base vem em percentual (ex.: 73,21), e
    quem converte e a importacao de CSV (issue #19). Por isso um valor acima de 1
    e recusado com a dica do percentual: e o erro mais provavel de quem digita.
    """
    texto = (bruto or "").strip().replace(" ", "")
    if not texto:
        return None, None
    try:
        valor = Decimal(texto.replace(",", "."))
    except InvalidOperation:
        return None, "O fator de potência precisa ser um número (ex.: 0,95)."

    if valor > 1:
        return None, (
            "O fator de potência vai de 0 a 1, não em percentual. "
            f"Se quis dizer {texto}%, digite {_como_decimal(valor / 100)}."
        )
    if valor < 0:
        return None, "O fator de potência não pode ser negativo."
    return valor, None


def validar(dados: dict) -> tuple[dict, list[str]]:
    """Confere os campos e devolve (valores_convertidos, erros)."""
    erros: list[str] = []
    valores: dict = {}

    texto_medidor = str(dados.get("id_medidor") or "").strip()
    medidor = None
    if not texto_medidor:
        erros.append("Escolha o medidor.")
    else:
        try:
            medidor = medidor_repository.buscar_por_id(int(texto_medidor))
        except ValueError:
            erros.append("Medidor inválido.")
        else:
            if medidor is None:
                erros.append("Medidor não encontrado.")
            elif not medidor.ativo:
                erros.append(
                    f"O medidor “{medidor.codigo}” está desativado e não aceita leitura nova."
                )
    valores["medidor"] = medidor

    data_hora, erro = converter_data_hora(dados.get("data_hora"))
    if erro:
        erros.append(erro)
    valores["data_hora"] = data_hora

    consumo, erro = converter_consumo(dados.get("consumo_kwh"))
    if erro:
        erros.append(erro)
    valores["consumo_kwh"] = consumo

    fator, erro = converter_fator_potencia(dados.get("fator_potencia"))
    if erro:
        erros.append(erro)
    valores["fator_potencia"] = fator

    # Regra 3: so da para conferir duplicidade com medidor e data_hora validos.
    if medidor is not None and data_hora is not None:
        if leitura_repository.existe(medidor.id, data_hora):
            erros.append(MENSAGEM_DUPLICADA.format(quando=_formatar(data_hora)))

    return valores, erros


def prever_para(medidor, data_hora: datetime) -> Decimal | None:
    """A previsao de consumo daquele medidor naquele instante (#26, regra 4).

    As leituras usadas sao as ANTERIORES a data_hora, nao as mais recentes do
    medidor: registrar uma leitura esquecida de ontem nao pode usar as de hoje
    como se fossem o passado dela.
    """
    anteriores = leitura_repository.anteriores_a(
        medidor.id, data_hora, LEITURAS_NECESSARIAS_PARA_PREVER
    )
    return previsao_service.prever(medidor, data_hora, anteriores)


def registrar(dados: dict) -> tuple[Leitura | None, list[str]]:
    """Registra uma leitura, com previsao e alertas. Devolve (leitura, erros).

    A ordem importa: a previsao e calculada ANTES de gravar, para a leitura ir
    ao banco ja com o consumo_previsto_kwh e nao precisar de um segundo UPDATE.
    Os alertas vem depois, porque precisam do id que so existe depois do commit.
    """
    valores, erros = validar(dados)
    if erros:
        return None, erros

    medidor = valores["medidor"]
    leitura = Leitura(
        id_medidor=medidor.id,
        data_hora=valores["data_hora"],
        consumo_kwh=valores["consumo_kwh"],
        fator_potencia=valores["fator_potencia"],
        consumo_previsto_kwh=prever_para(medidor, valores["data_hora"]),
    )

    try:
        leitura_repository.salvar(leitura)
    except IntegrityError:
        # A chave unica do banco fechou uma corrida que a validacao perdeu: dois
        # envios simultaneos da mesma leitura. Mensagem igual a do caminho normal.
        #
        # O desfazer() e obrigatorio: sem ele a sessao fica em "pending rollback"
        # e o resto da requisicao falha, mesmo com o erro tratado aqui.
        leitura_repository.desfazer()
        return None, [MENSAGEM_DUPLICADA.format(quando=_formatar(valores["data_hora"]))]

    alerta_service.abrir_para(leitura)
    return leitura, []


def _formatar(data_hora: datetime) -> str:
    """Data e hora como se le em portugues."""
    return data_hora.strftime("%d/%m/%Y às %H:%M")


def _como_decimal(valor: Decimal) -> str:
    """Numero com virgula e sem zeros a direita, como se escreve em portugues."""
    texto = f"{valor:f}"
    if "." in texto:
        texto = texto.rstrip("0").rstrip(".")
    return texto.replace(".", ",")
