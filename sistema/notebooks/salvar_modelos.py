"""Treina e salva os 4 modelos finais em ml/ (issue #25). Prazo duro: 01/11/2026.

Depende da comparacao da #21 (notebooks/treinar_modelos.py), que ja mediu os 5
algoritmos nos 4 setores. Aqui nao se compara mais nada: treina-se o algoritmo
escolhido, grava-se o pipeline e CONFERE-SE que o arquivo gravado volta do disco
funcionando.

Rodar dentro do container:

    docker compose exec app python notebooks/salvar_modelos.py

Saidas:
    ml/modelo_consumo_producao.pkl        (e os outros 3)
    data/processado/modelos_finais.json   -> metricas do que foi gravado
    docs/graficos/modelos_real_x_previsto.png
    docs/graficos/modelos_importancia_dos_atributos.png

DUAS DECISOES QUE ESTE SCRIPT APLICA, as duas contrariando a leitura literal da
issue — estao explicadas nos comentarios onde acontecem:

  1. Gradient Boosting NOS 4 SETORES, e nao "o de menor MAE de cada setor".
     O Random Forest tem o menor MAE em 2 deles, mas o .pkl dele tem 231 MB e o
     limite do GitHub e 100 MB POR ARQUIVO (ver escolher_algoritmo()).
  2. O modelo gravado e treinado SO no periodo de treino, nao no ano inteiro
     (ver treinar()).
"""

import json
import time
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")  # sem tela dentro do container
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from preparacao import ALVO, ATRIBUTOS, preparar_todos, separar
from treinar_modelos import metricas

RAIZ = Path(__file__).resolve().parent.parent
PASTA_ML = RAIZ / "ml"
PASTA_PROCESSADO = RAIZ / "data" / "processado"
PASTA_GRAFICOS = RAIZ / "docs" / "graficos"
SEMENTE = 42
# Regra 8: o registro de leitura com previsao tem de ficar abaixo de 500 ms.
# A previsao e so uma parte disso (ainda ha banco e renderizacao), entao o
# orcamento que este script cobra do modelo e bem menor.
MS_MAXIMO_POR_PREVISAO = 50.0
PERIODOS_DE_UMA_SEMANA = 7 * 96


def escolher_algoritmo() -> tuple[str, Pipeline]:
    """Gradient Boosting nos 4 setores.

    A issue #25 diz "escolher o algoritmo de menor MAE" de cada setor. Medido na
    #21, o menor MAE seria Random Forest na Producao (18,39% contra 20,23%) e na
    Manutencao (3,67% contra 4,02%). Mesmo assim o escolhido e o Gradient
    Boosting nos quatro, por uma restricao que a issue nao previa:

      - o .pkl do Random Forest tem 231 MB, e o limite do GitHub e 100 MB POR
        ARQUIVO. Os 4 dariam 924 MB num repositorio que precisa ser clonado na
        maquina do laboratorio (#41). O modelo simplesmente nao chega la;
      - e ele preve em 12,44 ms contra 0,23 ms (54x). Isso ainda caberia nos
        500 ms da regra 8 — o tamanho e que inviabiliza, nao o tempo.

    O preco e 1,8 ponto percentual de MAE% na Producao e 0,35 na Manutencao. Em
    troca, o Gradient Boosting e o MELHOR dos cinco no Administrativo e nas
    Utilidades, entao o mesmo algoritmo nos 4 setores tambem deixa a metodologia
    mais simples de defender: um pipeline, quatro treinos.
    """
    return "Gradient Boosting", Pipeline([
        ("escala", StandardScaler()),
        ("modelo", GradientBoostingRegressor(random_state=SEMENTE)),
    ])


def treinar(preparado: pd.DataFrame) -> tuple[Pipeline, dict, pd.DataFrame]:
    """Treina no periodo de treino e mede no de teste.

    POR QUE NAO RETREINAR NO ANO INTEIRO antes de gravar. E comum, em producao,
    retreinar no conjunto completo depois de escolher o modelo — mais dados,
    modelo um pouco melhor. Aqui nao, por dois motivos:

      1. HONESTIDADE DO NUMERO. As metricas que vao para o progress.json, para a
         apresentacao e para a defesa sao as deste .pkl exatamente. Retreinar
         depois de medir faria publicar o numero de um modelo que nao e o que
         esta gravado.
      2. A DEMONSTRACAO. Os dados de novembro e dezembro (#49) nunca foram
         vistos por este modelo. Na apresentacao da para dizer, sem ressalva,
         que o sistema esta prevendo periodos que o modelo nunca viu.
    """
    X_treino, y_treino, X_teste, y_teste = separar(preparado)
    _, pipeline = escolher_algoritmo()
    pipeline.fit(X_treino, y_treino)

    previsto = np.maximum(0.0, pipeline.predict(X_teste))
    medidas = metricas(y_teste, previsto, float(y_teste.mean()))

    comparacao = pd.DataFrame({
        "date": preparado.loc[X_teste.index, "date"].to_numpy(),
        "real": y_teste.to_numpy(),
        "previsto": previsto,
    })
    return pipeline, medidas, comparacao


def gravar(pipeline: Pipeline, setor: str) -> tuple[Path, dict]:
    """Grava o .pkl e CONFERE que ele volta do disco funcionando.

    Gravar sem reabrir e o jeito classico de descobrir no dia da apresentacao
    que o arquivo nao carrega. A conferencia aqui reproduz o que o
    PrevisaoService vai fazer: carregar o arquivo e prever UMA linha.
    """
    PASTA_ML.mkdir(parents=True, exist_ok=True)
    caminho = PASTA_ML / f"modelo_consumo_{setor}.pkl"
    joblib.dump(pipeline, caminho)

    recarregado = joblib.load(caminho)
    uma_linha = pd.DataFrame(
        [[12, 30, 2, 6, 0, 20.0, 19.5, 19.0, 18.5]], columns=ATRIBUTOS
    )
    do_disco = float(recarregado.predict(uma_linha)[0])
    da_memoria = float(pipeline.predict(uma_linha)[0])
    if not np.isclose(do_disco, da_memoria):
        raise SystemExit(
            f"{caminho.name}: o modelo recarregado preve {do_disco}, o da memoria {da_memoria}"
        )

    recarregado.predict(uma_linha)  # aquece antes de medir
    inicio = time.time()
    for _ in range(50):
        recarregado.predict(uma_linha)
    ms = (time.time() - inicio) / 50 * 1000
    if ms > MS_MAXIMO_POR_PREVISAO:
        raise SystemExit(f"{caminho.name}: {ms:.1f} ms por previsao, acima dos "
                         f"{MS_MAXIMO_POR_PREVISAO} ms de orcamento da regra 8")

    return caminho, {
        "arquivo": caminho.name,
        "mb": round(caminho.stat().st_size / 1024**2, 3),
        "ms_por_previsao": round(ms, 2),
        "confere_ao_recarregar": True,
    }


def grafico_real_x_previsto(comparacoes: dict[str, pd.DataFrame]) -> Path:
    """Uma semana do periodo de teste, real contra previsto, nos 4 setores."""
    figura, eixos = plt.subplots(len(comparacoes), 1, figsize=(13, 11), sharex=False)

    for eixo, (setor, comparacao) in zip(eixos, comparacoes.items()):
        semana = comparacao.iloc[:PERIODOS_DE_UMA_SEMANA]
        eixo.plot(semana["date"], semana["real"], linewidth=1.3, color="#1f4e79", label="real")
        eixo.plot(semana["date"], semana["previsto"], linewidth=1.1, color="#c0392b",
                  linestyle="--", label="previsto")
        erro = float((semana["real"] - semana["previsto"]).abs().mean())
        eixo.set_title(f"{setor.capitalize()} — primeira semana do periodo de teste "
                       f"(MAE da semana: {erro:.2f} kWh)", fontsize=10)
        eixo.set_ylabel("kWh / 15 min")
        eixo.grid(alpha=0.3)
        eixo.legend(fontsize=8, loc="upper right")

    figura.suptitle("Consumo real x previsto, em dados que o modelo nunca viu (issue #25)",
                    fontsize=11)
    figura.tight_layout()

    PASTA_GRAFICOS.mkdir(parents=True, exist_ok=True)
    caminho = PASTA_GRAFICOS / "modelos_real_x_previsto.png"
    figura.savefig(caminho, dpi=120)
    plt.close(figura)
    return caminho


def grafico_importancias(importancias: dict[str, np.ndarray]) -> Path:
    """Importancia dos 9 atributos em cada setor."""
    figura, eixo = plt.subplots(figsize=(11, 4.6))
    posicoes = np.arange(len(ATRIBUTOS))
    largura = 0.8 / len(importancias)

    for i, (setor, valores) in enumerate(importancias.items()):
        barras = eixo.bar(posicoes + i * largura, valores * 100, largura * 0.92, label=setor)
        eixo.bar_label(barras, fmt="%.0f", fontsize=6, padding=1)

    eixo.set_xticks(posicoes + largura * (len(importancias) - 1) / 2)
    eixo.set_xticklabels(ATRIBUTOS, rotation=20, ha="right")
    eixo.set_ylabel("importancia (%)")
    eixo.set_title("Importancia dos atributos no modelo de cada setor (issue #25)", fontsize=11)
    eixo.grid(axis="y", alpha=0.3)
    eixo.legend(fontsize=8)
    figura.tight_layout()

    PASTA_GRAFICOS.mkdir(parents=True, exist_ok=True)
    caminho = PASTA_GRAFICOS / "modelos_importancia_dos_atributos.png"
    figura.savefig(caminho, dpi=120)
    plt.close(figura)
    return caminho


def main() -> None:
    algoritmo, _ = escolher_algoritmo()
    preparados = preparar_todos()
    comparacoes, importancias, registro = {}, {}, {}

    print(f"algoritmo: {algoritmo} (scikit-learn {sklearn.__version__})\n")
    print(f"{'setor':<16}{'MAE':>9}{'MAE%':>8}{'RMSE':>9}{'R2':>8}{'MB':>8}{'ms':>8}")
    print("-" * 66)

    for setor, preparado in preparados.items():
        pipeline, medidas, comparacao = treinar(preparado)
        caminho, arquivo = gravar(pipeline, setor)

        comparacoes[setor] = comparacao
        importancias[setor] = pipeline.named_steps["modelo"].feature_importances_
        registro[setor] = {
            "algoritmo": algoritmo,
            "arquivo_modelo": caminho.name,
            **medidas,
            **arquivo,
            "media_no_teste_kwh": round(float(comparacao["real"].mean()), 3),
            "periodos_de_treino": int((preparado.conjunto == "treino").sum()),
            "periodos_de_teste": int((preparado.conjunto == "teste").sum()),
            "importancia_dos_atributos": {
                nome: round(float(valor), 4)
                for nome, valor in zip(ATRIBUTOS, importancias[setor])
            },
        }

        print(f"{setor:<16}{medidas['mae_kwh']:>9.3f}{medidas['mae_percentual']:>8.2f}"
              f"{medidas['rmse']:>9.3f}{medidas['r2']:>8.3f}{arquivo['mb']:>8.3f}"
              f"{arquivo['ms_por_previsao']:>8.2f}")

    grafico_semana = grafico_real_x_previsto(comparacoes)
    grafico_atributos = grafico_importancias(importancias)

    resultado = {
        "algoritmo": algoritmo,
        "versao_scikit_learn": sklearn.__version__,
        "semente": SEMENTE,
        "atributos": ATRIBUTOS,
        "alvo": ALVO,
        "treinado_em": "periodo de treino (10 primeiros meses), nunca no periodo de teste",
        "setores": registro,
        "graficos": [
            str(grafico_semana.relative_to(RAIZ)),
            str(grafico_atributos.relative_to(RAIZ)),
        ],
    }
    caminho_json = PASTA_PROCESSADO / "modelos_finais.json"
    caminho_json.write_text(json.dumps(resultado, indent=2, ensure_ascii=False) + "\n")

    total_mb = sum(d["mb"] for d in registro.values())
    print("-" * 66)
    print(f"os 4 .pkl somam {total_mb:.2f} MB "
          f"(o limite do GitHub e 100 MB por arquivo)")
    print("todos recarregados do disco e conferidos antes de sair daqui")

    print("\natributo mais importante em cada setor:")
    for setor, valores in importancias.items():
        ordem = np.argsort(valores)[::-1][:3]
        print(f"  {setor:<16}" + ", ".join(
            f"{ATRIBUTOS[i]} {valores[i] * 100:.0f}%" for i in ordem))

    print(f"\n{caminho_json.relative_to(RAIZ)}")
    for setor in registro:
        print(f"ml/{registro[setor]['arquivo_modelo']}")
    print(f"{grafico_semana.relative_to(RAIZ)}")
    print(f"{grafico_atributos.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
