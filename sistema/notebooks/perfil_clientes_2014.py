"""Perfil dos 370 clientes da ElectricityLoadDiagrams em 2014 (issue #43).

Le o LD2011_2014.txt (678 MB) EM PARTES, com chunksize, sem nunca carregar o
arquivo inteiro na memoria. Esse e o trecho "Big Data" da metodologia, por isso o
script mede e registra tamanho do arquivo, numero de linhas, tempo de leitura e
pico de memoria.

Rodar dentro do container, onde as versoes sao as mesmas que o sistema usa
(pandas 2.2.3, scikit-learn 1.5.2):

    docker compose exec app python notebooks/perfil_clientes_2014.py

Saidas:
    data/processado/perfil_clientes_2014.csv  -> media_kw e pct_zeros por cliente
    data/processado/perfil_clientes_2014.json -> as metricas da metodologia

Esta em notebooks/ porque e a analise de dados da issue #43, embora seja .py e
nao .ipynb: o notebook (#13) importa estas funcoes em vez de repetir o codigo,
para nao existirem duas versoes da mesma leitura.

Armadilhas desta base, todas tratadas aqui ou documentadas:
  - separador ponto e virgula, decimal virgula;
  - a unidade e kW MEDIO do periodo de 15 min; para kWh divide-se por 4 (issue #44);
  - clientes que entraram depois de 2011 tem zeros ate comecar a medir, e e isso
    que o filtro de menos de 1% de zeros em 2014 remove.
"""

import json
import resource
import sys
import time
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO = RAIZ / "data" / "bruto" / "LD2011_2014.txt"
PASTA_SAIDA = RAIZ / "data" / "processado"
ANO = 2014
# Medido neste arquivo, passando o tamanho pela linha de comando:
#
#   partes de    | n. de partes | tempo | pico de memoria
#   -------------|--------------|-------|----------------
#   2.000 linhas |           71 | 2,5 s |  141 MB
#   5.000 linhas |           29 | 2,3 s |  198 MB
#  20.000 linhas |            8 | 2,3 s |  415 MB
#   tudo de uma vez           1 | 2,5 s |  986 MB
#
# Ler tudo de uma vez custa 7x mais memoria e NAO economiza tempo: o gargalo e
# a conversao do decimal com virgula, nao o numero de partes. Por isso 5.000,
# que deixa folga de memoria sem nenhum custo de tempo.
TAMANHO_DA_PARTE = 5_000
# Regra do projeto: cliente "completo" tem menos de 1% de zeros no ano.
LIMITE_DE_ZEROS_PCT = 1.0


def perfilar(arquivo: Path, tamanho_da_parte: int = TAMANHO_DA_PARTE) -> tuple[pd.DataFrame, dict]:
    """Devolve (perfil, metricas), lendo o arquivo em partes.

    O perfil tem uma linha por cliente, com o consumo medio em kW e o
    percentual de periodos zerados no ano. As metricas sao os numeros que a
    metodologia do artigo precisa citar.
    """
    inicio = time.time()
    linhas_no_arquivo = 0
    linhas_no_ano = 0
    partes = 0
    soma_kw = None
    contagem_de_zeros = None

    leitor = pd.read_csv(
        arquivo,
        sep=";",
        decimal=",",
        index_col=0,
        parse_dates=True,
        chunksize=tamanho_da_parte,
    )

    for parte in leitor:
        partes += 1
        linhas_no_arquivo += len(parte)

        do_ano = parte[parte.index.year == ANO]
        if not do_ano.empty:
            linhas_no_ano += len(do_ano)
            soma_da_parte = do_ano.sum()
            zeros_da_parte = (do_ano == 0).sum()
            soma_kw = soma_da_parte if soma_kw is None else soma_kw + soma_da_parte
            contagem_de_zeros = (
                zeros_da_parte if contagem_de_zeros is None else contagem_de_zeros + zeros_da_parte
            )

        print(
            f"  parte {partes:>2}: {linhas_no_arquivo:>7,} linhas lidas, "
            f"{linhas_no_ano:>6,} de {ANO}  ({time.time() - inicio:.0f}s)",
            flush=True,
        )

    if linhas_no_ano == 0:
        raise SystemExit(f"nenhuma linha de {ANO} encontrada — confira o parse_dates")

    perfil = pd.DataFrame(
        {
            "media_kw": soma_kw / linhas_no_ano,
            "pct_zeros": contagem_de_zeros / linhas_no_ano * 100,
        }
    )
    perfil.index.name = "cliente"

    segundos = time.time() - inicio
    # ru_maxrss vem em bytes no macOS e em kilobytes no Linux (o container e Linux).
    pico_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    if sys.platform == "darwin":
        pico_mb = pico_mb / 1024

    metricas = {
        "arquivo": arquivo.name,
        "bytes_do_arquivo": arquivo.stat().st_size,
        "mb_do_arquivo": round(arquivo.stat().st_size / 1024**2, 1),
        "linhas_no_arquivo": linhas_no_arquivo,
        "linhas_em_2014": linhas_no_ano,
        "clientes": int(perfil.shape[0]),
        "tamanho_da_parte": tamanho_da_parte,
        "partes_lidas": partes,
        "segundos_de_leitura": round(segundos, 1),
        "pico_de_memoria_mb": round(pico_mb, 1),
        "limite_de_zeros_pct": LIMITE_DE_ZEROS_PCT,
    }
    return perfil, metricas


def main() -> None:
    if not ARQUIVO.exists():
        raise SystemExit(
            f"{ARQUIVO} nao existe. Baixe a base (o link esta no README) e "
            "descompacte o LD2011_2014.txt em data/bruto/."
        )

    # Tamanho da parte pela linha de comando, para medir o pico de memoria em
    # funcao dele (a evidencia de que a leitura em partes e o que viabiliza ler
    # um arquivo maior que a memoria que se quer gastar).
    tamanho = int(sys.argv[1]) if len(sys.argv) > 1 else TAMANHO_DA_PARTE

    print(f"lendo {ARQUIVO.name} em partes de {tamanho:,} linhas...")
    perfil, metricas = perfilar(ARQUIVO, tamanho)

    completos = perfil[perfil.pct_zeros < LIMITE_DE_ZEROS_PCT].sort_index()
    metricas["clientes_completos"] = int(completos.shape[0])
    metricas["lista_de_completos"] = completos.index.tolist()

    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
    caminho_csv = PASTA_SAIDA / "perfil_clientes_2014.csv"
    caminho_json = PASTA_SAIDA / "perfil_clientes_2014.json"
    perfil.sort_index().to_csv(caminho_csv, float_format="%.6f")
    caminho_json.write_text(json.dumps(metricas, indent=2, ensure_ascii=False) + "\n")

    print(f"\n{'=' * 62}")
    print(f"arquivo ........... {metricas['mb_do_arquivo']:,} MB")
    print(f"linhas ............ {metricas['linhas_no_arquivo']:,} no arquivo, "
          f"{metricas['linhas_em_2014']:,} em {ANO}")
    print(f"clientes .......... {metricas['clientes']}")
    print(f"leitura ........... {metricas['partes_lidas']} partes em "
          f"{metricas['segundos_de_leitura']}s")
    print(f"pico de memoria ... {metricas['pico_de_memoria_mb']:,} MB "
          f"(o arquivo tem {metricas['mb_do_arquivo']:,} MB)")
    print(f"completos ......... {metricas['clientes_completos']} de {metricas['clientes']} "
          f"com menos de {LIMITE_DE_ZEROS_PCT}% de zeros")
    print(f"{'=' * 62}")
    print(f"\n{caminho_csv.relative_to(RAIZ)}")
    print(f"{caminho_json.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
