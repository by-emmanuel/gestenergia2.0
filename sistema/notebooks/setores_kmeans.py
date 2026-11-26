"""Escolha dos 3 clientes por K-means e geracao dos CSVs dos setores (issue #44).

Parte do perfil dos 370 clientes que a issue #43 ja mediu
(data/processado/perfil_clientes_2014.csv), filtra a escala, le do arquivo de
678 MB SO as colunas dos candidatos (usecols), agrupa os perfis por K-means de 3
grupos e escolhe um cliente por grupo. Saida: um CSV por setor em data/setores/,
com as colunas `date` e `Usage_kWh`, mais os limites de consumo dos 4 setores.

Rodar dentro do container, onde as versoes sao as mesmas que o sistema usa
(pandas 2.2.3, scikit-learn 1.5.2, numpy 2.1.3):

    docker compose exec app python notebooks/setores_kmeans.py

Saidas:
    data/setores/administrativo.csv            -> date, Usage_kWh (35.040 linhas)
    data/setores/utilidades.csv                -> idem
    data/setores/manutencao.csv                -> idem
    data/processado/setores_kmeans.json        -> escolha, metricas e os 4 limites
    docs/graficos/setores_perfis_kmeans.png    -> conferencia dos 3 grupos
    docs/graficos/setores_horario_de_verao.png -> conferencia das 2 correcoes

Decisoes que este script aplica, todas da issue #44 e do CLAUDE.md:

  - FILTRAR A ESCALA ANTES DO K-MEANS. O K-means agrupa por *forma* do perfil,
    nao por escala; sem o filtro ele pode escolher um cliente 440x maior que a
    Producao e o painel fica ilegivel. Entram so os clientes completos com
    consumo medio entre 0,1x e 1,5x o da Producao (27,39 kWh por periodo).
  - A unidade da base e kW MEDIO do periodo de 15 min: para kWh, dividir por 4.
  - As duas armadilhas de horario de verao, confirmadas no arquivo pela #43:
    em 30/03/2014 os 4 periodos de 01:00 a 01:45 vem zerados (interpolar) e em
    26/10/2014 os mesmos 4 vem com a soma de duas horas (dividir por 2).
  - O limite de cada setor e o percentil 99 do consumo NO PERIODO DE TREINO
    (os 10 primeiros meses), nunca no ano todo nem no periodo de teste (regra 10).

O formato da data nos CSVs de setor e ISO (AAAA-MM-DD HH:MM:SS), que o pandas le
sem `dayfirst`. Nao e igual ao da siderurgica, que vem DD/MM/AAAA HH:MM e exige
`dayfirst=True` — as issues #13 e #19 precisam tratar os dois formatos, e e por
isso que a #19 detecta o formato pelo cabecalho.
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # sem tela dentro do container
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_GRANDE = RAIZ / "data" / "bruto" / "LD2011_2014.txt"
ARQUIVO_PERFIL = RAIZ / "data" / "processado" / "perfil_clientes_2014.csv"
ARQUIVO_STEEL = RAIZ / "data" / "bruto" / "Steel_industry_data.csv"
PASTA_SETORES = RAIZ / "data" / "setores"
PASTA_PROCESSADO = RAIZ / "data" / "processado"
PASTA_GRAFICOS = RAIZ / "docs" / "graficos"

ANO = 2014
TAMANHO_DA_PARTE = 5_000
LIMITE_DE_ZEROS_PCT = 1.0
# Consumo medio da Producao por periodo de 15 min, medido na siderurgica (secao
# 2.3 de docs/bases-de-dados.md). E a referencia de escala dos outros setores.
MEDIA_DA_PRODUCAO_KWH = 27.39
FAIXA_DE_ESCALA = (0.1, 1.5)
GRUPOS = 3
SEMENTE = 42
# Regra do projeto: 10 primeiros meses para treino, 2 ultimos para teste.
MESES_DE_TREINO = 10
PERCENTIL_DO_LIMITE = 0.99
PERIODOS_POR_SEMANA = 7 * 96

# As duas correcoes de horario de verao de 2014, confirmadas no arquivo pela #43.
DIA_QUE_PERDEU_UMA_HORA = "2014-03-30"
DIA_QUE_GANHOU_UMA_HORA = "2014-10-26"
HORAS_DA_MUDANCA = ("01:00", "01:45")


def candidatos(perfil: pd.DataFrame) -> tuple[list[str], dict]:
    """Clientes completos dentro da faixa de escala da Producao.

    Completo = menos de 1% de periodos zerados em 2014 (critério da #43).
    Na faixa = consumo medio em kWh entre 0,1x e 1,5x o da Producao.
    """
    completos = perfil[perfil.pct_zeros < LIMITE_DE_ZEROS_PCT]
    escala = completos.media_kw / 4 / MEDIA_DA_PRODUCAO_KWH
    minimo, maximo = FAIXA_DE_ESCALA
    na_faixa = completos[(escala >= minimo) & (escala <= maximo)].sort_index()

    metricas = {
        "clientes_na_base": int(perfil.shape[0]),
        "clientes_completos": int(completos.shape[0]),
        "candidatos": int(na_faixa.shape[0]),
        "faixa_de_escala": list(FAIXA_DE_ESCALA),
        "media_da_producao_kwh": MEDIA_DA_PRODUCAO_KWH,
    }
    return na_faixa.index.tolist(), metricas


def ler_series(arquivo: Path, clientes: list[str]) -> pd.DataFrame:
    """Le do arquivo de 678 MB so as colunas dos candidatos, em partes.

    Devolve as 35.040 linhas de 2014 em kWh (a base vem em kW medio do periodo
    de 15 min, por isso a divisao por 4), sem nenhuma correcao ainda.

    A primeira coluna do arquivo tem cabecalho vazio e guarda o carimbo de
    tempo; `MT_007` esta na posicao 7, entao as posicoes saem direto do codigo.
    """
    posicoes = [0] + [int(codigo.removeprefix("MT_")) for codigo in clientes]
    partes = []
    lidas = 0

    leitor = pd.read_csv(
        arquivo,
        sep=";",
        decimal=",",
        index_col=0,
        parse_dates=True,
        usecols=posicoes,
        chunksize=TAMANHO_DA_PARTE,
    )
    for parte in leitor:
        lidas += len(parte)
        do_ano = parte[parte.index.year == ANO]
        if not do_ano.empty:
            partes.append(do_ano)
        print(f"  {lidas:>7,} linhas lidas", end="\r", flush=True)

    if not partes:
        raise SystemExit(f"nenhuma linha de {ANO} encontrada — confira o parse_dates")

    series = pd.concat(partes).sort_index()
    series.index.name = "date"
    print(f"  {lidas:>7,} linhas lidas, {len(series):,} de {ANO}      ")
    return series / 4


def corrigir_horario_de_verao(series: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Aplica as duas correcoes de horario de verao de 2014.

    30/03: a hora que nao existiu vem zerada -> interpolar.
    26/10: a hora que aconteceu duas vezes vem somada -> dividir por 2.

    Nao mexe em nenhum outro periodo: os zeros de 30/03 sao do relogio, enquanto
    um zero em outro dia pode ser medicao real.
    """
    corrigida = series.copy()
    inicio, fim = HORAS_DA_MUDANCA

    faltou = corrigida.index.slice_indexer(
        f"{DIA_QUE_PERDEU_UMA_HORA} {inicio}", f"{DIA_QUE_PERDEU_UMA_HORA} {fim}"
    )
    zerados_antes = int((corrigida.iloc[faltou] == 0).sum().sum())
    corrigida.iloc[faltou] = np.nan
    corrigida = corrigida.interpolate(method="time", limit_direction="both")

    dobrou = corrigida.index.slice_indexer(
        f"{DIA_QUE_GANHOU_UMA_HORA} {inicio}", f"{DIA_QUE_GANHOU_UMA_HORA} {fim}"
    )
    corrigida.iloc[dobrou] = corrigida.iloc[dobrou] / 2

    relatorio = {
        "dia_que_perdeu_uma_hora": DIA_QUE_PERDEU_UMA_HORA,
        "periodos_interpolados": int(corrigida.iloc[faltou].size),
        "celulas_zeradas_antes": zerados_antes,
        "dia_que_ganhou_uma_hora": DIA_QUE_GANHOU_UMA_HORA,
        "periodos_divididos_por_2": int(corrigida.iloc[dobrou].size),
        "restou_algum_nan": bool(corrigida.isna().any().any()),
    }
    return corrigida, relatorio


def perfil_por_hora(series: pd.DataFrame) -> pd.DataFrame:
    """Perfil de 48 posicoes por cliente: 24 horas de dia util + 24 de fim de semana.

    Cada perfil e dividido pela propria media, entao o que sobra e a FORMA da
    curva e nao a escala — e isso que faz o K-means agrupar comportamento.
    """
    fim_de_semana = series.index.dayofweek >= 5
    hora = series.index.hour

    uteis = series[~fim_de_semana].groupby(hora[~fim_de_semana]).mean()
    fds = series[fim_de_semana].groupby(hora[fim_de_semana]).mean()
    uteis.index = [f"util_{h:02d}" for h in uteis.index]
    fds.index = [f"fds_{h:02d}" for h in fds.index]

    perfil = pd.concat([uteis, fds]).T
    return perfil.div(perfil.mean(axis=1), axis=0)


def agrupar(perfil: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    """K-means de 3 grupos sobre os perfis normalizados."""
    kmeans = KMeans(n_clusters=GRUPOS, random_state=SEMENTE, n_init=10)
    grupos = pd.Series(kmeans.fit_predict(perfil), index=perfil.index, name="grupo")
    centroides = pd.DataFrame(kmeans.cluster_centers_, columns=perfil.columns)
    return grupos, centroides


def nomear_grupos(centroides: pd.DataFrame) -> dict[int, str]:
    """Liga cada grupo do K-means a um setor, pela forma do seu centroide.

    Administrativo = maior diferenca entre dia util e fim de semana (menor razao
    fds/util). Utilidades = perfil mais achatado, de 24 horas (menor desvio
    relativo ao longo das 48 posicoes). Manutencao = o grupo que restar.
    """
    colunas_uteis = [c for c in centroides.columns if c.startswith("util_")]
    colunas_fds = [c for c in centroides.columns if c.startswith("fds_")]

    razao_fds = centroides[colunas_fds].mean(axis=1) / centroides[colunas_uteis].mean(axis=1)
    achatamento = centroides.std(axis=1) / centroides.mean(axis=1)

    administrativo = int(razao_fds.idxmin())
    restantes = [g for g in centroides.index if g != administrativo]
    utilidades = int(achatamento[restantes].idxmin())
    manutencao = next(g for g in restantes if g != utilidades)

    return {administrativo: "administrativo", utilidades: "utilidades", int(manutencao): "manutencao"}


def representante(perfil: pd.DataFrame, clientes: list[str], centroide: pd.Series) -> str:
    """Cliente do grupo mais proximo do centroide — o mais tipico do grupo."""
    distancias = ((perfil.loc[clientes] - centroide) ** 2).sum(axis=1)
    return str(distancias.idxmin())


def limite_do_setor(serie: pd.Series) -> dict:
    """Percentil 99 do periodo de TREINO, e quantos periodos do ano o passariam.

    Regra 10: o limite sai dos 10 primeiros meses. Usar o ano todo deixaria o
    periodo de teste influenciar o limite, que e a mesma familia de erro que
    treinar com dado de teste.
    """
    treino = serie[serie.index.month <= MESES_DE_TREINO]
    teste = serie[serie.index.month > MESES_DE_TREINO]
    limite = float(treino.quantile(PERCENTIL_DO_LIMITE))
    acima_no_ano = int((serie > limite).sum())

    return {
        "limite_consumo_kwh": round(limite, 3),
        "media_kwh": round(float(serie.mean()), 3),
        "media_no_teste_kwh": round(float(teste.mean()), 3),
        "maximo_kwh": round(float(serie.max()), 3),
        "periodos": int(serie.size),
        "periodos_de_treino": int(treino.size),
        "acima_do_limite_no_ano": acima_no_ano,
        "acima_do_limite_pct": round(acima_no_ano / serie.size * 100, 2),
        "alertas_por_semana": round(acima_no_ano / (serie.size / PERIODOS_POR_SEMANA), 1),
    }


def serie_da_producao() -> pd.Series:
    """Usage_kWh da siderurgica, ordenada no tempo.

    Duas armadilhas desta base (secao 2.2 de docs/bases-de-dados.md): o arquivo
    tem BOM, e as linhas NAO estao em ordem cronologica — a linha das 00:00 vem
    no fim de cada dia. Ordenar e obrigatorio antes de qualquer lag ou recorte.
    """
    steel = pd.read_csv(ARQUIVO_STEEL, encoding="utf-8-sig")
    steel["date"] = pd.to_datetime(steel["date"], dayfirst=True)
    return steel.sort_values("date").set_index("date")["Usage_kWh"]


def grafico_dos_grupos(
    perfil: pd.DataFrame,
    grupos: pd.Series,
    centroides: pd.DataFrame,
    nomes: dict[int, str],
    escolhidos: dict[str, str],
) -> Path:
    """Perfil medio de cada grupo e o cliente escolhido — a conferencia da #44."""
    figura, eixos = plt.subplots(1, GRUPOS, figsize=(15, 4.2), sharey=True)
    horas = range(24)

    for eixo, grupo in zip(eixos, sorted(nomes)):
        setor = nomes[grupo]
        escolhido = escolhidos[setor]
        centroide = centroides.loc[grupo]
        do_grupo = perfil[grupos == grupo]

        for cliente in do_grupo.index:
            eixo.plot(horas, do_grupo.loc[cliente, "util_00":"util_23"],
                      color="0.85", linewidth=0.5, zorder=1)

        eixo.plot(horas, centroide["util_00":"util_23"], color="#1f4e79",
                  linewidth=2.4, label="grupo, dia util", zorder=3)
        eixo.plot(horas, centroide["fds_00":"fds_23"], color="#1f4e79",
                  linewidth=2.0, linestyle="--", label="grupo, fim de semana", zorder=3)
        eixo.plot(horas, perfil.loc[escolhido, "util_00":"util_23"], color="#c0392b",
                  linewidth=1.8, label=f"{escolhido}, dia util", zorder=4)

        eixo.set_title(f"{setor.capitalize()} — grupo {grupo}, {len(do_grupo)} clientes\n"
                       f"escolhido: {escolhido}", fontsize=10)
        eixo.set_xlabel("hora do dia")
        eixo.set_xticks([0, 6, 12, 18, 23])
        eixo.grid(alpha=0.3)

    eixos[0].set_ylabel("consumo / media do cliente")
    eixos[0].legend(fontsize=8, loc="upper left")
    figura.suptitle(
        f"K-means de {GRUPOS} grupos sobre o perfil normalizado de {len(perfil)} candidatos "
        f"(issue #44)", fontsize=11)
    figura.tight_layout()

    PASTA_GRAFICOS.mkdir(parents=True, exist_ok=True)
    caminho = PASTA_GRAFICOS / "setores_perfis_kmeans.png"
    figura.savefig(caminho, dpi=120)
    plt.close(figura)
    return caminho


def grafico_do_horario_de_verao(
    antes: pd.DataFrame, depois: pd.DataFrame, escolhidos: dict[str, str]
) -> Path:
    """Os dois dias de mudanca de horario, antes e depois da correcao.

    O que tem de aparecer: o buraco de 30/03 preenchido e o pico de 26/10
    achatado ate a altura dos vizinhos.
    """
    dias = [
        (DIA_QUE_PERDEU_UMA_HORA, "30/03/2014 — a hora que nao existiu (interpolada)"),
        (DIA_QUE_GANHOU_UMA_HORA, "26/10/2014 — a hora dobrada (dividida por 2)"),
    ]
    figura, eixos = plt.subplots(2, 1, figsize=(12, 7))

    for eixo, (dia, titulo) in zip(eixos, dias):
        janela = slice(f"{dia} 00:00", f"{dia} 04:00")
        for setor, cliente in escolhidos.items():
            serie_antes = antes.loc[janela, cliente]
            serie_depois = depois.loc[janela, cliente]
            linha, = eixo.plot(serie_depois.index, serie_depois.values,
                               marker="o", markersize=3, linewidth=1.6,
                               label=f"{setor} ({cliente}) — corrigido")
            eixo.plot(serie_antes.index, serie_antes.values, linewidth=1.0,
                      linestyle=":", color=linha.get_color(),
                      label=f"{setor} ({cliente}) — original")

        eixo.axvspan(pd.Timestamp(f"{dia} 01:00"), pd.Timestamp(f"{dia} 01:45"),
                     color="#f1c40f", alpha=0.18)
        eixo.set_title(titulo, fontsize=10)
        eixo.set_ylabel("kWh por 15 min")
        eixo.grid(alpha=0.3)
        eixo.legend(fontsize=7, ncols=2)

    figura.suptitle("Conferencia das duas correcoes de horario de verao (issue #44)", fontsize=11)
    figura.tight_layout()

    PASTA_GRAFICOS.mkdir(parents=True, exist_ok=True)
    caminho = PASTA_GRAFICOS / "setores_horario_de_verao.png"
    figura.savefig(caminho, dpi=120)
    plt.close(figura)
    return caminho


def main() -> None:
    for arquivo in (ARQUIVO_GRANDE, ARQUIVO_PERFIL, ARQUIVO_STEEL):
        if not arquivo.exists():
            raise SystemExit(
                f"{arquivo.relative_to(RAIZ)} nao existe. Os links de download estao no "
                "README; o perfil sai de notebooks/perfil_clientes_2014.py (issue #43)."
            )

    perfil_da_43 = pd.read_csv(ARQUIVO_PERFIL, index_col="cliente")
    clientes, metricas = candidatos(perfil_da_43)
    print(f"candidatos: {len(clientes)} clientes completos entre "
          f"{FAIXA_DE_ESCALA[0]}x e {FAIXA_DE_ESCALA[1]}x a Producao")

    print(f"lendo {ARQUIVO_GRANDE.name} so com as {len(clientes)} colunas dos candidatos...")
    series = ler_series(ARQUIVO_GRANDE, clientes)
    if len(series) != 365 * 96:
        raise SystemExit(f"esperava {365 * 96:,} periodos em {ANO}, li {len(series):,}")

    corrigidas, correcoes = corrigir_horario_de_verao(series)
    print(f"horario de verao: {correcoes['celulas_zeradas_antes']:,} celulas zeradas "
          f"interpoladas em {DIA_QUE_PERDEU_UMA_HORA}, "
          f"{correcoes['periodos_divididos_por_2']} celulas divididas por 2 em "
          f"{DIA_QUE_GANHOU_UMA_HORA}")

    perfil = perfil_por_hora(corrigidas)
    grupos, centroides = agrupar(perfil)
    nomes = nomear_grupos(centroides)

    escolhidos = {
        nomes[grupo]: representante(
            perfil, grupos[grupos == grupo].index.tolist(), centroides.loc[grupo]
        )
        for grupo in sorted(nomes)
    }

    print("\ngrupos do K-means:")
    for grupo in sorted(nomes):
        setor = nomes[grupo]
        colunas_uteis = [c for c in centroides.columns if c.startswith("util_")]
        colunas_fds = [c for c in centroides.columns if c.startswith("fds_")]
        razao = centroides.loc[grupo, colunas_fds].mean() / centroides.loc[grupo, colunas_uteis].mean()
        achatamento = centroides.loc[grupo].std() / centroides.loc[grupo].mean()
        print(f"  grupo {grupo} -> {setor:<15} {int((grupos == grupo).sum()):>3} clientes, "
              f"fds/util = {razao:.2f}, achatamento = {achatamento:.2f}, "
              f"escolhido = {escolhidos[setor]}")

    PASTA_SETORES.mkdir(parents=True, exist_ok=True)
    setores = {}
    for setor, cliente in escolhidos.items():
        serie = corrigidas[cliente].rename("Usage_kWh")
        caminho = PASTA_SETORES / f"{setor}.csv"
        serie.to_csv(caminho, float_format="%.4f")

        setores[setor] = {
            "cliente": cliente,
            "grupo_kmeans": int(grupos[cliente]),
            "clientes_no_grupo": int((grupos == grupos[cliente]).sum()),
            "csv": str(caminho.relative_to(RAIZ)),
            "tem_fator_potencia": False,
            **limite_do_setor(serie),
        }

    setores["producao"] = {
        "cliente": None,
        "grupo_kmeans": None,
        "clientes_no_grupo": None,
        "csv": str(ARQUIVO_STEEL.relative_to(RAIZ)),
        "tem_fator_potencia": True,
        **limite_do_setor(serie_da_producao()),
    }

    grafico_grupos = grafico_dos_grupos(perfil, grupos, centroides, nomes, escolhidos)
    grafico_verao = grafico_do_horario_de_verao(series, corrigidas, escolhidos)

    metricas |= {
        "grupos": GRUPOS,
        "semente": SEMENTE,
        "atributos_do_kmeans": len(perfil.columns),
        "correcoes_de_horario_de_verao": correcoes,
        "percentil_do_limite": PERCENTIL_DO_LIMITE,
        "meses_de_treino": MESES_DE_TREINO,
        "setores": setores,
        "graficos": [
            str(grafico_grupos.relative_to(RAIZ)),
            str(grafico_verao.relative_to(RAIZ)),
        ],
    }
    caminho_json = PASTA_PROCESSADO / "setores_kmeans.json"
    caminho_json.write_text(json.dumps(metricas, indent=2, ensure_ascii=False) + "\n")

    print(f"\n{'=' * 78}")
    print(f"{'setor':<16}{'cliente':<9}{'media':>9}{'limite':>9}{'acima':>8}{'%':>7}{'/semana':>9}")
    print(f"{'-' * 78}")
    for setor in ("producao", "administrativo", "utilidades", "manutencao"):
        d = setores[setor]
        print(f"{setor:<16}{d['cliente'] or '-':<9}{d['media_kwh']:>9.2f}"
              f"{d['limite_consumo_kwh']:>9.2f}{d['acima_do_limite_no_ano']:>8}"
              f"{d['acima_do_limite_pct']:>7.2f}{d['alertas_por_semana']:>9.1f}")
    print(f"{'=' * 78}")
    print("\nmedia e limite em kWh por periodo de 15 min; 'acima' e no ano inteiro.")
    print("o limite sai do percentil 99 dos 10 primeiros meses (periodo de treino).")
    print(f"\n{caminho_json.relative_to(RAIZ)}")
    for setor in ("administrativo", "utilidades", "manutencao"):
        print(f"{setores[setor]['csv']}")
    print(f"{grafico_grupos.relative_to(RAIZ)}")
    print(f"{grafico_verao.relative_to(RAIZ)}")
    print("\nCONFERIR OS DOIS GRAFICOS antes de fechar a escolha (critérios da #44).")


if __name__ == "__main__":
    main()
