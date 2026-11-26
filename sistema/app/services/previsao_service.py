"""Previsao de consumo com o modelo de cada setor (issue #26, regras 4, 5 e 9).

Regra 9: os modelos sao carregados UMA VEZ SO, quando a aplicacao sobe. Carregar
o .pkl a cada leitura estouraria os 500 ms da regra 8 — o arquivo tem ~190 KB e
a leitura de disco custa mais que a previsao inteira, que leva 0,22 ms.

O caminho de uma previsao:

    leitura em t  ->  as 4 leituras ANTERIORES a t  ->  lag_1..lag_4
                      o relogio de t                ->  hora, minuto, dia_semana,
                                                        mes, fim_de_semana
                      o setor do medidor            ->  qual .pkl usar

Devolve None, sem erro, em todos estes casos (regras 4 e 9):

  - o medidor tem menos de 4 leituras anteriores;
  - o setor nao tem `arquivo_modelo`;
  - o arquivo nao existe em ml/, ou nao carregou.

A tela mostra "sem previsao ainda" nos quatro, que e o comportamento que a regra
4 descreve. Nenhum deles e erro: um medidor novo simplesmente ainda nao tem
historico, e um setor pode legitimamente nao ter modelo.
"""

import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

from ..models import Leitura, Medidor

registrador = logging.getLogger(__name__)

# CONTRATO COM O NOTEBOOK. Esta lista e identica — nos nomes e NA ORDEM — a
# ATRIBUTOS de notebooks/preparacao.py, que foi o que treinou os .pkl de ml/.
# Trocar um nome aqui sem trocar la faz o modelo receber colunas trocadas e
# prever lixo SEM LEVANTAR ERRO NENHUM. Se mexer em uma, mexa na outra e gere os
# .pkl de novo.
ATRIBUTOS = [
    "hora",
    "minuto",
    "dia_semana",
    "mes",
    "fim_de_semana",
    "lag_1",
    "lag_2",
    "lag_3",
    "lag_4",
]
# Regra 4: a previsao precisa de 4 leituras anteriores do mesmo medidor.
LEITURAS_NECESSARIAS = 4
# A coluna consumo_previsto_kwh e DECIMAL(10,3).
CASAS_DECIMAIS = Decimal("0.001")

# Os modelos carregados, por nome de arquivo. Preenchido uma vez em create_app().
_modelos: dict[str, object] = {}


def carregar_modelos(pasta: str | Path) -> dict:
    """Carrega todos os .pkl da pasta. Chamado uma vez, no create_app().

    Carrega a pasta inteira em vez de consultar os setores no banco porque, na
    hora em que a aplicacao sobe, o banco pode nem estar de pe — e a aplicacao
    tem de subir mesmo assim. A ligacao entre setor e arquivo e feita depois, a
    cada previsao, por `setor.arquivo_modelo`.

    Um .pkl que nao carrega NAO derruba a aplicacao: fica de fora do dicionario,
    o setor dele passa a devolver None e o registrador avisa. Um modelo gravado
    com outra versao do scikit-learn cai aqui — e e melhor o sistema subir sem
    previsao do que nao subir.
    """
    import joblib  # local: so a aplicacao com modelo paga o custo de importar

    _modelos.clear()
    caminho = Path(pasta)
    if not caminho.is_dir():
        registrador.warning("pasta de modelos %s nao existe: nenhum modelo carregado", caminho)
        return {"pasta": str(caminho), "carregados": [], "falharam": {}}

    falharam = {}
    for arquivo in sorted(caminho.glob("*.pkl")):
        try:
            _modelos[arquivo.name] = joblib.load(arquivo)
        except Exception as erro:  # noqa: BLE001 — qualquer falha aqui e "sem modelo"
            falharam[arquivo.name] = str(erro)
            registrador.warning("nao foi possivel carregar %s: %s", arquivo.name, erro)

    registrador.info("modelos carregados: %s", ", ".join(_modelos) or "nenhum")
    return {"pasta": str(caminho), "carregados": sorted(_modelos), "falharam": falharam}


def modelos_carregados() -> list[str]:
    """Nomes dos modelos em memoria. Serve a /saude e aos testes."""
    return sorted(_modelos)


def modelo_do_medidor(medidor: Medidor) -> object | None:
    """O modelo do setor do medidor, ou None se o setor nao tiver um utilizavel."""
    setor = medidor.setor
    if setor is None or not setor.arquivo_modelo:
        return None
    return _modelos.get(setor.arquivo_modelo)


def montar_atributos(data_hora: datetime, anteriores: list[Leitura]) -> pd.DataFrame:
    """Monta a linha de 9 atributos que o modelo espera.

    `anteriores` vem da mais nova para a mais antiga, que e a ordem em que o
    repositorio devolve: a mais nova e o lag_1 (15 minutos antes), a seguinte e
    o lag_2, e assim por diante.

    O calendario e o do periodo A PREVER, nao o da ultima leitura — o sistema
    conhece esse relogio de antemao, e foi assim que o modelo foi treinado.
    """
    lags = [float(leitura.consumo_kwh) for leitura in anteriores[:LEITURAS_NECESSARIAS]]
    return pd.DataFrame([linha_de_atributos(data_hora, lags)], columns=ATRIBUTOS)


def linha_de_atributos(data_hora: datetime, lags: list[float]) -> list:
    """Os 9 valores na ordem de ATRIBUTOS, para um periodo.

    `lags` vem do mais recente para o mais antigo: lag_1 e o periodo de 15
    minutos antes, lag_4 o de 60 minutos antes.
    """
    return [
        data_hora.hour,
        data_hora.minute,
        data_hora.weekday(),
        data_hora.month,
        int(data_hora.weekday() >= 5),
        *lags[:LEITURAS_NECESSARIAS],
    ]


def _arredondar(previsto: float) -> Decimal:
    """Regra 5: previsao nunca negativa, com as 3 casas da coluna."""
    return Decimal(str(max(0.0, previsto))).quantize(CASAS_DECIMAIS)


def prever_em_lote(
    medidor: Medidor, periodos: list[tuple[datetime, list[float]]]
) -> list[Decimal | None]:
    """Preve varios periodos de uma vez. Usado pela importacao de CSV (#19).

    Numa importacao os lags sao TODOS conhecidos de antemao — saem do proprio
    arquivo, nao de previsoes anteriores — entao da para montar a matriz inteira
    e chamar o modelo UMA vez. Prever linha a linha custaria 0,22 ms vezes o
    numero de linhas (quase 8 segundos num ano inteiro); em lote sao
    milissegundos.

    Cada item e (data_hora, lags). Quem nao tiver os 4 lags entra com None, sem
    ir ao modelo — e a regra 4 valendo igual para a importacao.
    """
    modelo = modelo_do_medidor(medidor)
    if modelo is None:
        return [None] * len(periodos)

    previsiveis = [
        (posicao, data_hora, lags)
        for posicao, (data_hora, lags) in enumerate(periodos)
        if len(lags) >= LEITURAS_NECESSARIAS
    ]
    resultado: list[Decimal | None] = [None] * len(periodos)
    if not previsiveis:
        return resultado

    matriz = pd.DataFrame(
        [linha_de_atributos(data_hora, lags) for _, data_hora, lags in previsiveis],
        columns=ATRIBUTOS,
    )
    try:
        previstos = modelo.predict(matriz)
    except Exception as erro:  # noqa: BLE001 — previsao quebrada nao derruba a importacao
        registrador.warning("falha ao prever em lote: %s", erro)
        return resultado

    for (posicao, _, _), previsto in zip(previsiveis, previstos):
        resultado[posicao] = _arredondar(float(previsto))
    return resultado


def prever(medidor: Medidor, data_hora: datetime, anteriores: list[Leitura]) -> Decimal | None:
    """Preve o consumo do periodo `data_hora`. None quando nao da para prever.

    Regra 5: a previsao nunca e negativa. O modelo e uma regressao e pode
    devolver um valor abaixo de zero quando extrapola; quem trunca e esta
    funcao, no mesmo ponto em que o notebook truncou antes de medir o MAE — se
    um truncasse e o outro nao, a metrica publicada nao seria a do sistema.
    """
    if len(anteriores) < LEITURAS_NECESSARIAS:
        return None

    modelo = modelo_do_medidor(medidor)
    if modelo is None:
        return None

    try:
        previsto = float(modelo.predict(montar_atributos(data_hora, anteriores))[0])
    except Exception as erro:  # noqa: BLE001 — previsao quebrada nao derruba a leitura
        registrador.warning(
            "falha ao prever para o medidor %s: %s", getattr(medidor, "codigo", "?"), erro
        )
        return None

    return _arredondar(previsto)
