"""Desempenho do registro de leitura com previsão (issue #29, regra 8 / RNF03).

Exige o banco de pé:  docker compose up -d db

Mede o caminho **inteiro**, do POST à resposta: validação, consulta das 4
leituras anteriores, previsão com o modelo, gravação, avaliação de alertas e
renderização. É esse o tempo que a regra 8 limita a 500 ms, não o do modelo
sozinho — o modelo prevê em 0,22 ms e nunca foi o risco aqui.

Usa os **.pkl de verdade** de `ml/`: medir com dublê não mediria nada.

Sobre medir tempo em teste: o número varia com a máquina e com a carga. Por isso
o teste afirma sobre a **mediana** e o **percentil 95** de várias repetições, e
não sobre uma medição isolada, que pegaria qualquer soluço do sistema. Os
valores medidos são impressos para poderem ser citados na apresentação.
"""

import statistics
import time
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.models import Medidor, Setor
from app.services import previsao_service
from tests.conftest import SENHA_OPERADOR

PRIMEIRA = datetime(2018, 1, 3, 12, 0)
MODELO_DA_PRODUCAO = "modelo_consumo_producao.pkl"
# Regra 8 / RNF03.
LIMITE_MS = 500
# Repeticoes medidas. 30 da uma mediana estavel sem deixar a suite lenta.
REPETICOES = 30
# Leituras registradas antes de medir, para a previsao realmente rodar (regra 4).
AQUECIMENTO = 5


@pytest.fixture(autouse=True)
def modelos_de_verdade(app):
    previsao_service.carregar_modelos(app.config["CAMINHO_MODELO"])
    if MODELO_DA_PRODUCAO not in previsao_service.modelos_carregados():
        pytest.skip("ml/ sem os modelos: rode notebooks/salvar_modelos.py (issue #25)")


@pytest.fixture
def producao(sessao):
    """Setor completo: com modelo e com limite, que é o caso mais caro.

    Sem limite não haveria comparação de alerta de consumo; sem modelo não
    haveria previsão. O teste precisa do caminho mais longo.
    """
    setor = Setor(
        nome="Produção",
        tem_fator_potencia=True,
        arquivo_modelo=MODELO_DA_PRODUCAO,
        limite_consumo_kwh=Decimal("122.980"),
    )
    medidor = Medidor(setor=setor, codigo="MED-PROD")
    sessao.add(medidor)
    sessao.commit()
    return medidor.id


@pytest.fixture
def operador(cliente, usuarios, producao):
    cliente.post(
        "/login",
        data={"email": "operador@gestenergia.local", "senha": SENHA_OPERADOR},
        follow_redirects=True,
    )
    return cliente


def registrar(cliente, id_medidor, passo, fator=""):
    quando = PRIMEIRA + timedelta(minutes=15 * passo)
    return cliente.post(
        "/leituras/nova",
        data={
            "id_medidor": str(id_medidor),
            "data_hora": quando.strftime("%Y-%m-%dT%H:%M"),
            "consumo_kwh": f"{20 + passo % 7}",
            "fator_potencia": fator,
        },
        follow_redirects=True,
    )


def medir(cliente, id_medidor, fator="") -> list[float]:
    """Registra AQUECIMENTO + REPETICOES leituras e devolve os tempos em ms.

    As de aquecimento não entram na conta: as 4 primeiras nem chegam a prever
    (regra 4) e a primeira requisição paga importações e conexão que as
    seguintes já encontram prontas.
    """
    for passo in range(AQUECIMENTO):
        registrar(cliente, id_medidor, passo, fator)

    tempos = []
    for passo in range(AQUECIMENTO, AQUECIMENTO + REPETICOES):
        inicio = time.perf_counter()
        resposta = registrar(cliente, id_medidor, passo, fator)
        tempos.append((time.perf_counter() - inicio) * 1000)
        assert resposta.status_code == 200
    return tempos


def relatar(titulo: str, tempos: list[float]) -> dict:
    """Imprime e devolve as estatísticas. O print sai com `pytest -s`."""
    ordenados = sorted(tempos)
    medidas = {
        "mediana": statistics.median(ordenados),
        "media": statistics.fmean(ordenados),
        "p95": ordenados[int(len(ordenados) * 0.95) - 1],
        "maximo": ordenados[-1],
        "minimo": ordenados[0],
    }
    print(f"\n{titulo} ({len(tempos)} registros, limite da regra 8: {LIMITE_MS} ms)")
    for nome, valor in medidas.items():
        print(f"  {nome:<8} {valor:>7.1f} ms")
    return medidas


# ---------------------------------------------------------------------------
# RNF03 — o critério da issue
# ---------------------------------------------------------------------------


def test_registro_com_previsao_fica_abaixo_de_500ms(operador, producao):
    """Critério da #29: mede o tempo e falha acima de 500 ms."""
    medidas = relatar("Registro com previsão", medir(operador, producao))

    assert medidas["mediana"] < LIMITE_MS, (
        f"mediana de {medidas['mediana']:.0f} ms, acima dos {LIMITE_MS} ms da regra 8"
    )
    assert medidas["p95"] < LIMITE_MS, (
        f"percentil 95 de {medidas['p95']:.0f} ms, acima dos {LIMITE_MS} ms da regra 8"
    )


def test_nenhum_registro_isolado_estoura_o_limite(operador, producao):
    """A regra 8 é por requisição, não em média: o pior caso também conta."""
    tempos = medir(operador, producao)
    pior = max(tempos)

    assert pior < LIMITE_MS, f"o registro mais lento levou {pior:.0f} ms"


def test_registro_que_abre_os_dois_alertas_tambem_cabe(operador, producao):
    """O caminho mais caro: previsão + dois alertas gravados."""
    medidas = relatar("Registro abrindo alerta de fator", medir(operador, producao, fator="0,80"))

    assert medidas["p95"] < LIMITE_MS


# ---------------------------------------------------------------------------
# De onde vem o tempo — serve ao artigo e à defesa
# ---------------------------------------------------------------------------


def test_a_previsao_e_uma_fracao_pequena_do_tempo(operador, producao, app):
    """Mostra que o gargalo não é o modelo.

    Se um dia este teste falhar, a conclusão muda: aí sim valeria discutir o
    algoritmo. Hoje o modelo prevê em fração de milissegundo e o resto do tempo
    é banco e renderização.
    """
    from app.models import Leitura

    for passo in range(AQUECIMENTO):
        registrar(operador, producao, passo)

    with app.app_context():
        from app.repositories import medidor_repository

        medidor = medidor_repository.buscar_por_id(producao)
        anteriores = [
            Leitura(id_medidor=producao, consumo_kwh=Decimal(str(20 + i))) for i in range(4)
        ]
        previsao_service.prever(medidor, PRIMEIRA, anteriores)  # aquece

        inicio = time.perf_counter()
        for _ in range(REPETICOES):
            previsao_service.prever(medidor, PRIMEIRA, anteriores)
        ms_do_modelo = (time.perf_counter() - inicio) / REPETICOES * 1000

    print(f"\nPrevisão isolada: {ms_do_modelo:.2f} ms "
          f"({ms_do_modelo / LIMITE_MS * 100:.1f}% do orçamento da regra 8)")

    assert ms_do_modelo < LIMITE_MS / 10, (
        f"a previsão sozinha leva {ms_do_modelo:.1f} ms — mais de 10% do orçamento"
    )
