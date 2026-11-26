"""Monta os dados do painel (issue #20).

O painel nao tem regra propria: ele compoe o que os outros servicos sabem. As
decisoes que moram aqui sao de APRESENTACAO, e estao aqui e nao no template
porque o template so exibe.

Sobre a janela de tempo: as bases sao de 2018 (siderurgica) e 2014
(ElectricityLoadDiagrams), entao um filtro "ultimos 7 dias" contado de hoje
devolveria tela vazia. A janela e por CONTAGEM de leituras, ancorada na mais
recente do medidor. Com cadencia de 15 minutos a conversao e direta: 96 leituras
sao um dia, 672 sao uma semana.
"""

from decimal import Decimal

from ..models import Medidor, Setor, TipoAlerta
from ..repositories import alerta_repository, leitura_repository, medidor_repository
from ..repositories import setor_repository
from .leitura_service import fator_abaixo_do_minimo

# Janelas oferecidas no filtro: (chave, rotulo, quantidade de leituras).
# A cadencia das duas bases e de 15 minutos: 4 por hora, 96 por dia.
JANELAS = (
    ("dia", "Último dia (96 leituras)", 96),
    ("semana", "Última semana (672)", 672),
    ("mes", "Últimos 30 dias (2880)", 2880),
)
JANELA_PADRAO = "dia"

# Cores validadas para a pagina (ver o commit da #20): uma escala de 3, com um
# significado por cor. O azul e o laranja sao as series do grafico; o laranja
# serve tambem ao alerta de consumo, porque e a serie prevista que o dispara.
COR_REAL = "#2a78d6"
COR_PREVISTO = "#eb6834"
CORES_POR_TIPO_DE_ALERTA = {
    TipoAlerta.CONSUMO_ACIMA_LIMITE: COR_PREVISTO,
    TipoAlerta.FATOR_POTENCIA_BAIXO: "#4a3aa7",
}

ROTULOS_DE_TIPO = {
    TipoAlerta.CONSUMO_ACIMA_LIMITE: "Consumo acima do limite",
    TipoAlerta.FATOR_POTENCIA_BAIXO: "Fator de potência baixo",
}


def quantidade_da_janela(chave: str | None) -> int:
    """Quantas leituras a janela escolhida cobre. Chave invalida cai no padrao."""
    quantidades = {chave_valida: quantidade for chave_valida, _, quantidade in JANELAS}
    return quantidades.get(chave, quantidades[JANELA_PADRAO])


def escolher_setor(id_bruto: str | None) -> Setor | None:
    """Resolve o setor do filtro. Vazio ou invalido devolve None, que e 'todos'."""
    texto = (id_bruto or "").strip()
    if not texto:
        return None
    try:
        return setor_repository.buscar_por_id(int(texto))
    except ValueError:
        return None


def medidores_para_o_filtro(setor: Setor | None) -> list[Medidor]:
    """Medidores oferecidos, limitados ao setor escolhido quando houver um."""
    if setor is None:
        return medidor_repository.listar()
    return medidor_repository.listar_por_setor(setor.id, apenas_ativos=False)


def escolher_medidor(id_bruto: str | None, disponiveis: list[Medidor]) -> Medidor | None:
    """Resolve o medidor do grafico.

    Sem escolha explicita, abre no medidor que TEM a leitura mais recente, e nao
    no primeiro em ordem alfabetica. A diferenca e pratica: com os 4 medidores do
    banco.sql, o primeiro em ordem e o MED-ADMI, que pode nao ter leitura — o
    painel abria vazio com dado disponivel no medidor ao lado.
    """
    texto = (id_bruto or "").strip()
    if texto:
        for medidor in disponiveis:
            if str(medidor.id) == texto:
                return medidor

    com_dado = leitura_repository.medidor_com_leitura_mais_recente(
        [medidor.id for medidor in disponiveis]
    )
    if com_dado is not None:
        for medidor in disponiveis:
            if medidor.id == com_dado:
                return medidor
    return disponiveis[0] if disponiveis else None


def serie(medidor: Medidor | None, quantidade: int) -> dict:
    """Dados do grafico: consumo real e previsto do medidor, em ordem de tempo.

    O previsto vem como None onde ainda nao existe, e o Chart.js corta a linha
    ali em vez de ligar pontos distantes — que e o certo: nao houve previsao
    naquele instante, e inventar continuidade seria mentir sobre o dado.
    """
    if medidor is None:
        return {"rotulos": [], "real": [], "previsto": [], "tem_previsto": False}

    leituras = leitura_repository.serie_do_medidor(medidor.id, quantidade)
    return {
        "rotulos": [l.data_hora.strftime("%d/%m %H:%M") for l in leituras],
        "real": [_numero(l.consumo_kwh) for l in leituras],
        "previsto": [_numero(l.consumo_previsto_kwh) for l in leituras],
        "tem_previsto": any(l.consumo_previsto_kwh is not None for l in leituras),
    }


def tabela(medidor: Medidor | None, quantidade: int) -> list[dict]:
    """A mesma serie em forma de tabela.

    Nao e enfeite: e o par acessivel do grafico. Todo valor que o grafico mostra
    precisa ser alcancavel sem passar o mouse e sem depender de cor.
    """
    if medidor is None:
        return []

    linhas = []
    for leitura in leitura_repository.serie_do_medidor(medidor.id, quantidade):
        linhas.append(
            {
                "quando": leitura.data_hora.strftime("%d/%m/%Y %H:%M"),
                "real": leitura.consumo_kwh,
                "previsto": leitura.consumo_previsto_kwh,
                "fator": leitura.fator_potencia,
                "fator_baixo": fator_abaixo_do_minimo(leitura),
            }
        )
    return linhas[::-1]  # a tabela le do mais recente para o mais antigo


def alertas_abertos(setor: Setor | None) -> list[dict]:
    """Alertas abertos, já com rótulo e cor por tipo resolvidos.

    A cor vem acompanhada SEMPRE do rotulo em texto: cor sozinha nao identifica
    nada para quem nao distingue as duas, nem em impressao em preto e branco.
    """
    alertas = alerta_repository.listar_abertos(setor.id if setor else None)
    return [
        {
            "alerta": alerta,
            "rotulo": ROTULOS_DE_TIPO[alerta.tipo],
            "cor": CORES_POR_TIPO_DE_ALERTA[alerta.tipo],
            "medidor": alerta.leitura.medidor.codigo,
            "setor": alerta.leitura.medidor.setor.nome,
        }
        for alerta in alertas
    ]


def totais_de_alerta(setor: Setor | None) -> list[dict]:
    """Quantos alertas abertos de cada tipo, sempre com os dois tipos listados.

    Mostrar o tipo com zero e proposital: "0 alertas de fator de potencia" e uma
    informacao; a ausencia da linha seria ambigua.
    """
    contagem = alerta_repository.contar_abertos_por_tipo(setor.id if setor else None)
    return [
        {
            "tipo": tipo,
            "rotulo": ROTULOS_DE_TIPO[tipo],
            "cor": CORES_POR_TIPO_DE_ALERTA[tipo],
            "total": contagem.get(tipo, 0),
        }
        for tipo in TipoAlerta
    ]


def _numero(valor: Decimal | None) -> float | None:
    """Decimal para float, porque o JSON do grafico nao conhece Decimal.

    O arredondamento em 3 casas acompanha DECIMAL(10,3) do banco: nao se ganha
    precisao mostrando mais do que foi gravado.
    """
    return None if valor is None else round(float(valor), 3)
