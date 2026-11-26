"""Treino e comparacao dos modelos, um laco por setor (issue #21).

Cinco candidatos — modelo ingenuo, Regressao Linear, Arvore de Decisao, Random
Forest e Gradient Boosting — rodados pela MESMA funcao `avaliar(df)` nos 4
setores, com os mesmos 9 atributos e a mesma separacao por tempo.

Rodar dentro do container, onde as versoes sao as mesmas que o sistema usa
(scikit-learn 1.5.2 — a mesma do requirements.txt, senao os .pkl da #25 nao
carregam):

    docker compose exec app python notebooks/treinar_modelos.py

Saidas:
    data/processado/metricas_modelos.json      -> a tabela completa
    docs/graficos/setores_perfil_por_hora.png  -> perfil medio por hora
    docs/graficos/modelos_mae_percentual.png   -> comparacao entre algoritmos

POR QUE O MODELO INGENUO ESTA AQUI. Ele preve "o proximo periodo e igual ao
anterior" — repete o lag_1. Numa serie de 15 em 15 minutos isso ja acerta muito,
porque o consumo muda devagar. Um algoritmo que nao bate o ingenuo do PROPRIO
setor nao esta aprendendo nada util, por melhor que o R2 pareca. E a referencia
honesta, e e por setor porque cada serie tem a sua inercia.

POR QUE MAE% E NAO SO MAE. O MAE em kWh nao e comparavel entre setores: as
Utilidades consomem 6,65 kWh por periodo e a Manutencao 29,60, entao errar
1 kWh significa coisas muito diferentes nos dois. O MAE% (MAE dividido pelo
consumo medio do setor NO TESTE) e o que diz em qual setor o metodo funciona
melhor.
"""

import json
import tempfile
import time
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")  # sem tela dentro do container
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeRegressor

from preparacao import ALVO, ATRIBUTOS, preparar_todos, separar

RAIZ = Path(__file__).resolve().parent.parent
PASTA_PROCESSADO = RAIZ / "data" / "processado"
PASTA_GRAFICOS = RAIZ / "docs" / "graficos"
SEMENTE = 42
INGENUO = "Ingenuo (repete o anterior)"


def candidatos() -> dict[str, Pipeline]:
    """Os 4 algoritmos treinaveis, cada um como pipeline completo.

    O StandardScaler entra em todos por uniformidade — ele e indiferente para as
    arvores e necessario para a regressao linear, e deixa cada .pkl da #25
    autossuficiente: recebe as 9 colunas cruas de ATRIBUTOS e devolve kWh.
    """
    return {
        "Regressao Linear": Pipeline([
            ("escala", StandardScaler()),
            ("modelo", LinearRegression()),
        ]),
        "Arvore de Decisao": Pipeline([
            ("escala", StandardScaler()),
            ("modelo", DecisionTreeRegressor(random_state=SEMENTE)),
        ]),
        "Random Forest": Pipeline([
            ("escala", StandardScaler()),
            ("modelo", RandomForestRegressor(random_state=SEMENTE, n_jobs=-1)),
        ]),
        "Gradient Boosting": Pipeline([
            ("escala", StandardScaler()),
            ("modelo", GradientBoostingRegressor(random_state=SEMENTE)),
        ]),
    }


def metricas(y_verdadeiro: pd.Series, y_previsto: np.ndarray, media_no_teste: float) -> dict:
    """MAE, MAE%, RMSE e R2 — sempre no periodo de teste.

    A previsao e truncada em 0 antes de medir (regra 5: previsao nunca e
    negativa). Medir o modelo cru e o sistema com valores diferentes seria
    publicar um numero que o sistema nao entrega.
    """
    previsto = np.maximum(0.0, y_previsto)
    mae = mean_absolute_error(y_verdadeiro, previsto)
    return {
        "mae_kwh": round(float(mae), 4),
        "mae_percentual": round(float(mae / media_no_teste * 100), 2),
        "rmse": round(float(np.sqrt(mean_squared_error(y_verdadeiro, previsto))), 4),
        "r2": round(float(r2_score(y_verdadeiro, previsto)), 4),
    }


def avaliar(df: pd.DataFrame) -> pd.DataFrame:
    """Tabela de metricas de UM setor, com os 5 candidatos na mesma separacao.

    Recebe o que `preparar(df)` devolveu. Devolve uma linha por algoritmo,
    ordenada do menor para o maior MAE%.
    """
    X_treino, y_treino, X_teste, y_teste = separar(df)
    media_no_teste = float(y_teste.mean())

    # O ingenuo nao treina: a previsao dele e o proprio lag_1 do periodo.
    linhas = [{
        "algoritmo": INGENUO,
        "segundos_de_treino": 0.0,
        "ms_por_previsao": 0.0,
        "mb_do_pkl": 0.0,
        **metricas(y_teste, X_teste["lag_1"].to_numpy(), media_no_teste),
    }]

    for nome, pipeline in candidatos().items():
        inicio = time.time()
        pipeline.fit(X_treino, y_treino)
        segundos = time.time() - inicio

        previsto = pipeline.predict(X_teste)

        # Tempo de UMA previsao, que e o que a regra 8 cobra: o sistema preve
        # uma leitura por vez, nao 5.856 de uma vez.
        uma_linha = X_teste.iloc[[0]]
        pipeline.predict(uma_linha)  # aquece antes de medir
        inicio = time.time()
        for _ in range(50):
            pipeline.predict(uma_linha)
        ms = (time.time() - inicio) / 50 * 1000

        with tempfile.NamedTemporaryFile(suffix=".pkl") as temporario:
            joblib.dump(pipeline, temporario.name)
            mb = Path(temporario.name).stat().st_size / 1024**2

        linhas.append({
            "algoritmo": nome,
            "segundos_de_treino": round(segundos, 1),
            "ms_por_previsao": round(ms, 2),
            "mb_do_pkl": round(mb, 1),
            **metricas(y_teste, previsto, media_no_teste),
        })

    return pd.DataFrame(linhas).sort_values("mae_percentual").reset_index(drop=True)


def grafico_perfil_por_hora(preparados: dict[str, pd.DataFrame]) -> Path:
    """Perfil medio por hora dos 4 setores, em kWh e normalizado."""
    figura, (absoluto, relativo) = plt.subplots(1, 2, figsize=(13, 4.6))

    for setor, df in preparados.items():
        por_hora = df.groupby(df["date"].dt.hour)[ALVO].mean()
        absoluto.plot(por_hora.index, por_hora.values, marker="o", markersize=3, label=setor)
        relativo.plot(por_hora.index, por_hora.values / por_hora.mean(),
                      marker="o", markersize=3, label=setor)

    absoluto.set_title("Consumo medio por hora (kWh por periodo de 15 min)", fontsize=10)
    absoluto.set_ylabel("kWh")
    relativo.set_title("O mesmo, dividido pela media de cada setor", fontsize=10)
    relativo.set_ylabel("consumo / media do setor")
    relativo.axhline(1.0, color="0.6", linewidth=0.8, linestyle="--")

    for eixo in (absoluto, relativo):
        eixo.set_xlabel("hora do dia")
        eixo.set_xticks([0, 6, 12, 18, 23])
        eixo.grid(alpha=0.3)
        eixo.legend(fontsize=8)

    figura.suptitle("Perfil medio por hora dos 4 setores (issue #21)", fontsize=11)
    figura.tight_layout()

    PASTA_GRAFICOS.mkdir(parents=True, exist_ok=True)
    caminho = PASTA_GRAFICOS / "setores_perfil_por_hora.png"
    figura.savefig(caminho, dpi=120)
    plt.close(figura)
    return caminho


def grafico_comparacao(tabelas: dict[str, pd.DataFrame]) -> Path:
    """MAE% de cada algoritmo em cada setor, com o ingenuo destacado."""
    algoritmos = [INGENUO, *candidatos()]
    setores = list(tabelas)
    largura = 0.8 / len(algoritmos)

    figura, eixo = plt.subplots(figsize=(11, 4.6))
    posicoes = np.arange(len(setores))

    for i, algoritmo in enumerate(algoritmos):
        valores = [
            float(tabelas[setor].set_index("algoritmo").loc[algoritmo, "mae_percentual"])
            for setor in setores
        ]
        barras = eixo.bar(posicoes + i * largura, valores, largura * 0.92, label=algoritmo,
                          color="0.6" if algoritmo == INGENUO else None,
                          hatch="//" if algoritmo == INGENUO else None)
        eixo.bar_label(barras, fmt="%.1f", fontsize=6, padding=1)

    eixo.set_xticks(posicoes + largura * (len(algoritmos) - 1) / 2)
    eixo.set_xticklabels(setores)
    eixo.set_ylabel("MAE% (menor e melhor)")
    eixo.set_title("Erro percentual por setor e por algoritmo, no periodo de teste (issue #21)",
                   fontsize=11)
    eixo.grid(axis="y", alpha=0.3)
    eixo.legend(fontsize=8, ncols=5, loc="upper center", bbox_to_anchor=(0.5, -0.1))
    figura.tight_layout()

    PASTA_GRAFICOS.mkdir(parents=True, exist_ok=True)
    caminho = PASTA_GRAFICOS / "modelos_mae_percentual.png"
    figura.savefig(caminho, dpi=120, bbox_inches="tight")
    plt.close(figura)
    return caminho


def main() -> None:
    preparados = preparar_todos()
    tabelas = {}

    for setor, df in preparados.items():
        print(f"\n{'=' * 86}\n{setor.upper()}  —  {len(df):,} periodos, "
              f"media de {df[df.conjunto == 'teste'][ALVO].mean():.2f} kWh no teste\n{'=' * 86}")
        tabela = avaliar(df)
        tabelas[setor] = tabela

        print(f"{'algoritmo':<28}{'MAE':>9}{'MAE%':>8}{'RMSE':>9}{'R2':>8}"
              f"{'treino':>9}{'ms/prev':>9}{'MB':>7}")
        print("-" * 86)
        for _, linha in tabela.iterrows():
            print(f"{linha.algoritmo:<28}{linha.mae_kwh:>9.3f}{linha.mae_percentual:>8.2f}"
                  f"{linha.rmse:>9.3f}{linha.r2:>8.3f}{linha.segundos_de_treino:>8.1f}s"
                  f"{linha.ms_por_previsao:>9.2f}{linha.mb_do_pkl:>7.1f}")

    grafico_perfil = grafico_perfil_por_hora(preparados)
    grafico_mae = grafico_comparacao(tabelas)

    resultado = {
        "versao_scikit_learn": __import__("sklearn").__version__,
        "semente": SEMENTE,
        "atributos": ATRIBUTOS,
        "alvo": ALVO,
        "setores": {setor: tabela.to_dict("records") for setor, tabela in tabelas.items()},
        "graficos": [
            str(grafico_perfil.relative_to(RAIZ)),
            str(grafico_mae.relative_to(RAIZ)),
        ],
    }
    caminho_json = PASTA_PROCESSADO / "metricas_modelos.json"
    caminho_json.write_text(json.dumps(resultado, indent=2, ensure_ascii=False) + "\n")

    print(f"\n{'=' * 86}\nMELHOR DE CADA SETOR, E QUANTO ELE BATE O INGENUO\n{'=' * 86}")
    print(f"{'setor':<16}{'melhor algoritmo':<22}{'MAE%':>8}{'ingenuo':>10}{'ganho':>9}")
    print("-" * 86)
    for setor, tabela in tabelas.items():
        melhor = tabela.iloc[0]
        ingenuo = tabela.set_index("algoritmo").loc[INGENUO, "mae_percentual"]
        ganho = (ingenuo - melhor.mae_percentual) / ingenuo * 100
        print(f"{setor:<16}{melhor.algoritmo:<22}{melhor.mae_percentual:>8.2f}"
              f"{ingenuo:>10.2f}{ganho:>8.1f}%")

    print(f"\n{caminho_json.relative_to(RAIZ)}")
    print(f"{grafico_perfil.relative_to(RAIZ)}")
    print(f"{grafico_mae.relative_to(RAIZ)}")
    print("\nA escolha e a gravacao dos 4 .pkl sao a issue #25.")


if __name__ == "__main__":
    main()
