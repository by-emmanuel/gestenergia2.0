"""Pre-processamento comum aos 4 setores (issue #13).

Uma unica funcao `preparar(df)` serve a siderurgica e aos 3 CSVs de
data/setores/, porque ela so precisa de duas colunas: `date` e `Usage_kWh`.
Tudo o que a siderurgica tem a mais (CO2, potencias reativas, fator de potencia,
NSM, WeekStatus, Day_of_week, Load_Type) e DESCARTADO de proposito:

  - CO2, potencias reativas e fator de potencia do mesmo periodo VAZAM a
    resposta — sao medidos junto com o consumo que se quer prever;
  - e, mais decisivo, so existem em 1 dos 4 setores. Um atributo que so um setor
    tem nao pode entrar num pipeline que precisa ser identico nos quatro.

Rodar dentro do container, onde as versoes sao as mesmas que o sistema usa:

    docker compose exec app python notebooks/preparacao.py

Saida:
    data/processado/leituras_preprocessado.csv  -> os 4 setores empilhados

ATENCAO AO CONTRATO COM A #26. A lista ATRIBUTOS abaixo e a mesma coisa que o
PrevisaoService vai montar a cada leitura, com os MESMOS NOMES e na MESMA ORDEM.
Mudar um nome aqui sem mudar la faz o modelo receber colunas trocadas e prever
lixo sem levantar erro nenhum.
"""

import json
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
PASTA_SETORES = RAIZ / "data" / "setores"
PASTA_PROCESSADO = RAIZ / "data" / "processado"
ARQUIVO_STEEL = RAIZ / "data" / "bruto" / "Steel_industry_data.csv"

# Os 9 atributos de entrada, iguais nos 4 setores. ORDEM E NOMES FIXOS (#26).
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
ALVO = "Usage_kWh"
LAGS = 4
# Regra do projeto: 10 primeiros meses para treino, 2 ultimos para teste.
# Separacao POR TEMPO, nunca embaralhada: embaralhar deixaria o modelo ver o
# futuro de um dia enquanto preve o passado do mesmo dia.
MESES_DE_TREINO = 10

SETORES = {
    "producao": ARQUIVO_STEEL,
    "administrativo": PASTA_SETORES / "administrativo.csv",
    "utilidades": PASTA_SETORES / "utilidades.csv",
    "manutencao": PASTA_SETORES / "manutencao.csv",
}


def carregar(caminho: Path) -> pd.DataFrame:
    """Le um CSV de setor e devolve so `date` e `Usage_kWh`, ordenado no tempo.

    Os dois formatos de data que o projeto tem convivem aqui:

      - a siderurgica vem DD/MM/AAAA HH:MM, com BOM, e EM ORDEM TROCADA — a
        linha das 00:00 vem no fim de cada dia (secao 2.2 de
        docs/bases-de-dados.md). Ordenar e obrigatorio ANTES de qualquer lag;
      - os CSVs de data/setores/ vem em ISO, ja ordenados.

    Ordenar sempre, nos dois casos, sai mais barato que lembrar qual precisa.
    """
    da_siderurgica = caminho == ARQUIVO_STEEL
    df = pd.read_csv(caminho, encoding="utf-8-sig" if da_siderurgica else "utf-8")
    df["date"] = pd.to_datetime(df["date"], dayfirst=da_siderurgica)
    return df[["date", ALVO]].sort_values("date").reset_index(drop=True)


def preparar(df: pd.DataFrame) -> pd.DataFrame:
    """Monta os 9 atributos e marca treino/teste. Precisa so de `date` e `Usage_kWh`.

    Cada linha e um periodo de 15 min a prever: os atributos de calendario sao
    os DO PROPRIO periodo (que o sistema conhece de antemao — e so o relogio) e
    os lags sao os 4 periodos ANTERIORES.

    E exatamente a situacao da regra 4: tendo as leituras de t-3, t-2, t-1 e t,
    o sistema preve t+1 com o calendario de t+1 e aquelas 4 leituras como
    lag_4..lag_1. Por isso o alvo e o consumo da propria linha e nao um shift(-1)
    — as duas formas sao a mesma, e esta e a que casa com o PrevisaoService sem
    deslocamento nenhum para lembrar depois.
    """
    if not {"date", ALVO}.issubset(df.columns):
        faltando = {"date", ALVO} - set(df.columns)
        raise ValueError(f"preparar precisa das colunas {faltando}")

    pronto = df[["date", ALVO]].sort_values("date").reset_index(drop=True)

    pronto["hora"] = pronto["date"].dt.hour
    pronto["minuto"] = pronto["date"].dt.minute
    pronto["dia_semana"] = pronto["date"].dt.dayofweek
    pronto["mes"] = pronto["date"].dt.month
    pronto["fim_de_semana"] = (pronto["dia_semana"] >= 5).astype(int)

    for lag in range(1, LAGS + 1):
        pronto[f"lag_{lag}"] = pronto[ALVO].shift(lag)

    # As 4 primeiras linhas nao tem as 4 leituras anteriores. E a mesma regra 4
    # que faz a tela mostrar "sem previsao ainda" para um medidor novo.
    pronto = pronto.dropna(subset=[f"lag_{lag}" for lag in range(1, LAGS + 1)])

    # O corte e ancorado no primeiro dia do primeiro mes da serie, e nao na
    # primeira linha que sobrou: as 4 linhas removidas acima deslocariam o corte
    # em uma hora e jogariam os 4 primeiros periodos do 11o mes para o treino.
    primeiro_mes = pronto["date"].min().normalize().replace(day=1)
    corte = primeiro_mes + pd.DateOffset(months=MESES_DE_TREINO)
    pronto["conjunto"] = (pronto["date"] >= corte).map({True: "teste", False: "treino"})

    return pronto[["date", "conjunto", *ATRIBUTOS, ALVO]].reset_index(drop=True)


def separar(preparado: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    """Devolve (X_treino, y_treino, X_teste, y_teste) na ordem fixa de ATRIBUTOS."""
    treino = preparado[preparado["conjunto"] == "treino"]
    teste = preparado[preparado["conjunto"] == "teste"]
    return treino[ATRIBUTOS], treino[ALVO], teste[ATRIBUTOS], teste[ALVO]


def preparar_todos() -> dict[str, pd.DataFrame]:
    """Roda carregar + preparar nos 4 setores, com a mesma funcao para todos."""
    preparados = {}
    for setor, caminho in SETORES.items():
        if not caminho.exists():
            raise SystemExit(
                f"{caminho.relative_to(RAIZ)} nao existe. Os CSVs dos setores saem de "
                "notebooks/setores_kmeans.py (issue #44)."
            )
        preparados[setor] = preparar(carregar(caminho))
    return preparados


def main() -> None:
    preparados = preparar_todos()

    empilhado = pd.concat(
        [df.assign(setor=setor) for setor, df in preparados.items()], ignore_index=True
    )
    empilhado = empilhado[["setor", "date", "conjunto", *ATRIBUTOS, ALVO]]

    PASTA_PROCESSADO.mkdir(parents=True, exist_ok=True)
    caminho_csv = PASTA_PROCESSADO / "leituras_preprocessado.csv"
    empilhado.to_csv(caminho_csv, index=False, float_format="%.4f")

    resumo = {}
    print(f"{'setor':<16}{'linhas':>9}{'treino':>9}{'teste':>8}  {'periodo de teste':<34}")
    print("-" * 76)
    for setor, df in preparados.items():
        treino = df[df.conjunto == "treino"]
        teste = df[df.conjunto == "teste"]
        resumo[setor] = {
            "linhas": len(df),
            "treino": len(treino),
            "teste": len(teste),
            "primeira": str(df.date.min()),
            "ultima": str(df.date.max()),
            "corte": str(teste.date.min()),
            "media_no_teste_kwh": round(float(teste[ALVO].mean()), 3),
        }
        print(f"{setor:<16}{len(df):>9,}{len(treino):>9,}{len(teste):>8,}  "
              f"{teste.date.min()} -> {teste.date.max()}")

    caminho_json = PASTA_PROCESSADO / "preprocessamento.json"
    caminho_json.write_text(
        json.dumps(
            {"atributos": ATRIBUTOS, "alvo": ALVO, "lags": LAGS,
             "meses_de_treino": MESES_DE_TREINO, "setores": resumo},
            indent=2, ensure_ascii=False,
        ) + "\n"
    )

    print("-" * 76)
    print(f"atributos ({len(ATRIBUTOS)}): {', '.join(ATRIBUTOS)}")
    print(f"alvo: {ALVO}")
    print(f"\n{caminho_csv.relative_to(RAIZ)} ({caminho_csv.stat().st_size / 1024**2:.1f} MB)")
    print(f"{caminho_json.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
