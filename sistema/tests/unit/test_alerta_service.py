"""Testes das regras de alerta sem banco (issue #27, regras 1 e 2).

`avaliar` monta os alertas e não grava nada, então a regra inteira se testa aqui,
sem MySQL.

Casos de borda obrigatórios pelo CLAUDE.md cobertos neste arquivo: **fator 0,91 /
0,92 / 0,93**, **consumo igual e acima do limite**, e leitura sem fator de
potência (que não pode gerar alerta nem erro).
"""

from datetime import datetime
from decimal import Decimal

import pytest

from app.models import Leitura, Medidor, Setor, TipoAlerta
from app.services import alerta_service

QUANDO = datetime(2018, 1, 3, 12, 30)


def leitura_de(previsto=None, fator=None, limite="100.000", nome="Produção"):
    """Leitura já gravada (com id), ligada a um medidor e a um setor."""
    medidor = Medidor(id=1, codigo="MED-PROD", id_setor=1, ativo=True)
    medidor.setor = Setor(
        id=1, nome=nome, ativo=True,
        limite_consumo_kwh=None if limite is None else Decimal(limite),
    )
    leitura = Leitura(
        id=7,
        id_medidor=1,
        data_hora=QUANDO,
        consumo_kwh=Decimal("50.000"),
        fator_potencia=None if fator is None else Decimal(fator),
        consumo_previsto_kwh=None if previsto is None else Decimal(previsto),
    )
    leitura.medidor = medidor
    return leitura


def tipos(alertas):
    return [a.tipo for a in alertas]


# ---------------------------------------------------------------------------
# Regra 1 — fator de potência
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fator, abaixo",
    [
        ("0.919", True),
        ("0.91", True),
        ("0.92", False),   # exatamente o mínimo NÃO é violação
        ("0.921", False),
        ("0.93", False),
        ("0.000", True),
        ("1.000", False),
    ],
)
def test_fator_abaixo_do_minimo(fator, abaixo):
    assert alerta_service.fator_abaixo_do_minimo(leitura_de(fator=fator)) is abaixo


def test_fator_nulo_nao_e_violacao_e_nao_da_erro():
    """Regra 1: hoje só a Produção tem o dado; os outros setores vêm com NULL."""
    assert alerta_service.fator_abaixo_do_minimo(leitura_de(fator=None)) is False


@pytest.mark.parametrize("fator, abre", [("0.91", True), ("0.92", False), ("0.93", False)])
def test_alerta_de_fator_nos_tres_casos_de_borda(fator, abre):
    alertas = alerta_service.avaliar(leitura_de(fator=fator))
    assert (TipoAlerta.FATOR_POTENCIA_BAIXO in tipos(alertas)) is abre


def test_leitura_sem_fator_nao_abre_alerta_de_fator():
    assert alerta_service.avaliar(leitura_de(fator=None)) == []


def test_alerta_de_fator_guarda_o_valor_e_o_minimo():
    """valor_observado e limite_referencia existem para auditoria depois."""
    alerta = alerta_service.avaliar(leitura_de(fator="0.73"))[0]
    assert alerta.valor_observado == Decimal("0.73")
    assert alerta.limite_referencia == Decimal("0.92")
    assert alerta.id_leitura == 7
    assert "0,73" in alerta.mensagem and "0,92" in alerta.mensagem


# ---------------------------------------------------------------------------
# Regra 2 — consumo previsto acima do limite do setor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "previsto, abre",
    [
        ("99.999", False),
        ("100.000", False),  # igual ao limite NÃO gera alerta
        ("100.001", True),
        ("150.000", True),
    ],
)
def test_consumo_igual_e_acima_do_limite(previsto, abre):
    alertas = alerta_service.avaliar(leitura_de(previsto=previsto, limite="100.000"))
    assert (TipoAlerta.CONSUMO_ACIMA_LIMITE in tipos(alertas)) is abre


def test_sem_previsao_nao_abre_alerta_de_consumo():
    """Regra 4: menos de 4 leituras, ou setor sem modelo. Não é violação."""
    assert alerta_service.avaliar(leitura_de(previsto=None, limite="1.000")) == []


def test_setor_sem_limite_nao_abre_alerta_de_consumo():
    """Enquanto limite_consumo_kwh for NULL, não há com o que comparar."""
    assert alerta_service.avaliar(leitura_de(previsto="9999.000", limite=None)) == []


def test_o_alerta_compara_com_o_limite_daquele_setor():
    """Critério da #27: o limite é o do setor do medidor, não um valor global."""
    sem_alerta = alerta_service.avaliar(leitura_de(previsto="50.000", limite="100.000"))
    com_alerta = alerta_service.avaliar(leitura_de(previsto="50.000", limite="11.959"))
    assert sem_alerta == []
    assert tipos(com_alerta) == [TipoAlerta.CONSUMO_ACIMA_LIMITE]


def test_alerta_de_consumo_guarda_o_previsto_e_o_limite():
    alerta = alerta_service.avaliar(
        leitura_de(previsto="130.500", limite="122.980", nome="Produção")
    )[0]
    assert alerta.valor_observado == Decimal("130.500")
    assert alerta.limite_referencia == Decimal("122.980")
    assert "130,5" in alerta.mensagem and "122,98" in alerta.mensagem
    assert "Produção" in alerta.mensagem


def test_o_alerta_de_consumo_olha_o_previsto_e_nao_o_medido():
    """O sentido do sistema é avisar antes: quem dispara é a previsão."""
    leitura = leitura_de(previsto="10.000", limite="100.000")
    leitura.consumo_kwh = Decimal("999.000")  # medido altíssimo
    assert alerta_service.avaliar(leitura) == []


# ---------------------------------------------------------------------------
# Os dois juntos
# ---------------------------------------------------------------------------


def test_uma_leitura_pode_abrir_os_dois_alertas():
    alertas = alerta_service.avaliar(leitura_de(previsto="200.000", limite="100.000", fator="0.80"))
    assert tipos(alertas) == [TipoAlerta.CONSUMO_ACIMA_LIMITE, TipoAlerta.FATOR_POTENCIA_BAIXO]


def test_leitura_normal_nao_abre_nada():
    assert alerta_service.avaliar(leitura_de(previsto="50.000", limite="100.000", fator="0.98")) == []


def test_avaliar_nao_grava_nada(monkeypatch):
    """`avaliar` é pura de propósito: quem grava é `abrir_para`."""
    def explodir(*_):
        raise AssertionError("avaliar não pode tocar no repositório")

    monkeypatch.setattr(alerta_service.alerta_repository, "salvar_varios", explodir)
    assert len(alerta_service.avaliar(leitura_de(previsto="200.000", fator="0.80"))) == 2


def test_abrir_para_sem_alertas_nao_chama_o_banco(monkeypatch):
    """Leitura normal é o caso comum: não vale abrir transação à toa."""
    def explodir(*_):
        raise AssertionError("não devia gravar quando não há alerta")

    monkeypatch.setattr(alerta_service.alerta_repository, "salvar_varios", explodir)
    assert alerta_service.abrir_para(leitura_de(previsto="1.000", fator="0.99")) == []
