"""Fluxo completo de previsão e alertas pelas telas (issues #26 e #27).

Exige o banco de pé:  docker compose up -d db

Este arquivo usa os **.pkl de verdade** de `ml/`, e não dublês — é o único teste
que prova que o modelo treinado no notebook carrega no sistema e prevê. Se a
versão do scikit-learn divergir entre o `requirements.txt` e a que gerou os
arquivos, é aqui que aparece.

Os casos de borda das regras estão em `tests/unit/test_alerta_service.py` e
`tests/unit/test_previsao_service.py`; aqui o que se testa é o encanamento:
registrar leitura pela tela grava previsão e abre alerta.
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Alerta, Leitura, Medidor, Setor, StatusAlerta, TipoAlerta
from app.services import previsao_service
from tests.conftest import SENHA_OPERADOR

PRIMEIRA = datetime(2018, 1, 3, 12, 0)
MODELO_DA_PRODUCAO = "modelo_consumo_producao.pkl"


@pytest.fixture(autouse=True)
def modelos_de_verdade(app):
    """Garante os .pkl reais carregados, como o create_app faz ao subir."""
    previsao_service.carregar_modelos(app.config["CAMINHO_MODELO"])
    if MODELO_DA_PRODUCAO not in previsao_service.modelos_carregados():
        pytest.skip("ml/ sem os modelos: rode notebooks/salvar_modelos.py (issue #25)")


@pytest.fixture
def producao(sessao):
    """Setor de Produção com modelo, limite e um medidor ativo."""
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


@pytest.fixture
def limite_de(sessao, producao):
    """Troca o limite do setor dentro do teste.

    Existe por causa de um achado da #27, medido e registrado no `progress.json`:
    **o modelo da Produção nunca prevê acima dos 122,98 kWh do setor** — o maior
    valor que ele consegue produzir, com os lags no máximo da série, é 116,01. O
    limite foi calibrado no percentil 99 do consumo REAL (regra 10) e a regra 2
    compara com o PREVISTO, que é uma média condicional e não alcança os picos.

    Enquanto essa calibração não for decidida, os testes de alerta de consumo
    usam um limite que o modelo alcança: o que se prova aqui é o encanamento
    (prever → comparar → abrir alerta), não a calibração.
    """

    def ajustar(valor):
        setor = sessao.get(Medidor, producao).setor
        setor.limite_consumo_kwh = Decimal(valor)
        sessao.commit()

    return ajustar


def registrar(cliente, id_medidor, minutos, consumo, fator=""):
    """Registra uma leitura a `minutos` do instante inicial."""
    quando = PRIMEIRA + timedelta(minutes=minutos)
    return cliente.post(
        "/leituras/nova",
        data={
            "id_medidor": str(id_medidor),
            "data_hora": quando.strftime("%Y-%m-%dT%H:%M"),
            "consumo_kwh": consumo,
            "fator_potencia": fator,
        },
        follow_redirects=True,
    )


def semear(cliente, id_medidor, consumos, fator=""):
    """Registra uma sequência de leituras de 15 em 15 minutos."""
    for passo, consumo in enumerate(consumos):
        registrar(cliente, id_medidor, passo * 15, consumo, fator)


def leituras_de(sessao):
    return list(sessao.scalars(select(Leitura).order_by(Leitura.data_hora)))


def alertas_de(sessao):
    return list(sessao.scalars(select(Alerta).order_by(Alerta.id)))


# ---------------------------------------------------------------------------
# Regra 4 — a previsão só começa na quinta leitura
# ---------------------------------------------------------------------------


def test_as_4_primeiras_leituras_ficam_sem_previsao(operador, producao, sessao, recarregar):
    """Regra 4: com menos de 4 anteriores, a tela mostra 'sem previsão ainda'."""
    semear(operador, producao, ["10", "11", "12", "13"])
    recarregar()

    assert [l.consumo_previsto_kwh for l in leituras_de(sessao)] == [None] * 4


def test_a_quinta_leitura_ja_vem_com_previsao(operador, producao, sessao, recarregar):
    semear(operador, producao, ["10", "11", "12", "13", "14"])
    recarregar()

    previstos = [l.consumo_previsto_kwh for l in leituras_de(sessao)]
    assert previstos[:4] == [None] * 4
    assert previstos[4] is not None
    assert previstos[4] >= 0  # regra 5


def test_a_previsao_aparece_no_painel(operador, producao, sessao, recarregar):
    semear(operador, producao, ["10", "11", "12", "13", "14"])
    recarregar()

    pagina = operador.get("/painel").get_data(as_text=True)

    assert "Consumo previsto" in pagina
    assert "sem previsão ainda" not in pagina


def test_leitura_registrada_fora_de_ordem_nao_usa_o_futuro(operador, producao, sessao, recarregar):
    """A previsão usa as leituras ANTERIORES àquele instante, não as mais recentes.

    Registra 5 leituras, depois uma esquecida no meio do caminho: a previsão dela
    tem de sair das 4 que vieram antes dela no tempo, não das últimas do medidor.
    """
    semear(operador, producao, ["10", "11", "12", "13", "14", "15"])
    registrar(operador, producao, minutos=7, consumo="99")  # entre a 1ª e a 2ª
    recarregar()

    esquecida = next(l for l in leituras_de(sessao) if l.consumo_kwh == Decimal("99.000"))
    # Antes dela só existe UMA leitura no tempo (a das 12:00), então regra 4.
    assert esquecida.consumo_previsto_kwh is None


# ---------------------------------------------------------------------------
# Regra 2 — alerta de consumo acima do limite do setor
# ---------------------------------------------------------------------------


def test_consumo_dentro_do_limite_nao_abre_alerta(operador, producao, sessao, recarregar):
    semear(operador, producao, ["10", "11", "12", "13", "14"])
    recarregar()

    assert alertas_de(sessao) == []


def test_consumo_previsto_acima_do_limite_abre_alerta(
    operador, producao, limite_de, sessao, recarregar
):
    limite_de("50.000")
    semear(operador, producao, ["150", "155", "157", "156", "157"])
    recarregar()

    alertas = alertas_de(sessao)
    assert [a.tipo for a in alertas] == [TipoAlerta.CONSUMO_ACIMA_LIMITE]
    assert alertas[0].status == StatusAlerta.ABERTO
    assert alertas[0].limite_referencia == Decimal("50.000")
    assert alertas[0].valor_observado > Decimal("50.000")


def test_o_alerta_compara_com_o_limite_daquele_setor(
    operador, producao, limite_de, sessao, recarregar
):
    """Regra 2: o limite é o do setor do medidor, não um valor global."""
    limite_de("500.000")
    semear(operador, producao, ["150", "155", "157", "156", "157"])
    recarregar()

    assert alertas_de(sessao) == []


def test_o_alerta_aparece_no_painel(operador, producao, limite_de, sessao, recarregar):
    limite_de("50.000")
    semear(operador, producao, ["150", "155", "157", "156", "157"])
    recarregar()

    pagina = operador.get("/painel").get_data(as_text=True)

    assert "acima do limite" in pagina.lower()


# ---------------------------------------------------------------------------
# Regra 1 — alerta de fator de potência
# ---------------------------------------------------------------------------


def test_fator_abaixo_de_092_abre_alerta_na_primeira_leitura(
    operador, producao, sessao, recarregar
):
    """O alerta de fator não depende de previsão: olha o valor medido."""
    registrar(operador, producao, minutos=0, consumo="10", fator="0,91")
    recarregar()

    alertas = alertas_de(sessao)
    assert [a.tipo for a in alertas] == [TipoAlerta.FATOR_POTENCIA_BAIXO]
    assert alertas[0].valor_observado == Decimal("0.910")


@pytest.mark.parametrize("fator", ["0,92", "0,93", ""])
def test_fator_no_minimo_ou_ausente_nao_abre_alerta(
    operador, producao, sessao, recarregar, fator
):
    """Exatamente 0,92 não é violação; e sem o dado não gera alerta nem erro."""
    registrar(operador, producao, minutos=0, consumo="10", fator=fator)
    recarregar()

    assert alertas_de(sessao) == []


def test_uma_leitura_pode_abrir_os_dois_alertas(
    operador, producao, limite_de, sessao, recarregar
):
    limite_de("50.000")
    semear(operador, producao, ["150", "155", "157", "156"])
    registrar(operador, producao, minutos=4 * 15, consumo="157", fator="0,80")
    recarregar()

    assert {a.tipo for a in alertas_de(sessao)} == {
        TipoAlerta.CONSUMO_ACIMA_LIMITE,
        TipoAlerta.FATOR_POTENCIA_BAIXO,
    }


# ---------------------------------------------------------------------------
# Regra 9 — setor sem modelo
# ---------------------------------------------------------------------------


def test_setor_sem_modelo_registra_leitura_sem_previsao_e_sem_erro(
    cliente, usuarios, sessao, recarregar
):
    """Regra 9: setor sem arquivo_modelo não é erro — é 'sem previsão ainda'."""
    setor = Setor(nome="Utilidades", arquivo_modelo=None, limite_consumo_kwh=Decimal("11.959"))
    medidor = Medidor(setor=setor, codigo="MED-UTIL")
    sessao.add(medidor)
    sessao.commit()

    cliente.post(
        "/login",
        data={"email": "operador@gestenergia.local", "senha": SENHA_OPERADOR},
        follow_redirects=True,
    )
    semear(cliente, medidor.id, ["5", "6", "7", "8", "9"])
    recarregar()

    assert len(leituras_de(sessao)) == 5
    assert [l.consumo_previsto_kwh for l in leituras_de(sessao)] == [None] * 5
    assert alertas_de(sessao) == []


# A regra 8 (tempo de resposta) tem arquivo proprio: tests/system/test_desempenho.py,
# da issue #29, que mede repeticoes e afirma sobre mediana e percentil 95 em vez
# de sobre uma medicao isolada.
