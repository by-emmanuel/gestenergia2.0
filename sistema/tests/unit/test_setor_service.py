"""Testes das regras de setor sem banco (issue #16).

A conversao do limite e pura, entao e testada direto. A validacao consulta o
repositorio para barrar nome repetido, e por isso o repositorio e trocado por um
dublê.
"""

from decimal import Decimal

import pytest

from app.models import Setor
from app.services import setor_service


@pytest.fixture
def sem_setor_cadastrado(monkeypatch):
    """Faz o validar() achar que nenhum nome esta em uso."""
    monkeypatch.setattr(setor_service.setor_repository, "buscar_por_nome", lambda nome: None)


@pytest.fixture
def com_setor(monkeypatch):
    """Faz o validar() achar um setor ja cadastrado com aquele nome."""

    def configurar(nome: str, id_setor: int = 7):
        existente = Setor(id=id_setor, nome=nome)
        monkeypatch.setattr(
            setor_service.setor_repository, "buscar_por_nome", lambda n: existente
        )
        return existente

    return configurar


# ---------------------------------------------------------------------------
# Conversao do limite (regra 10)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "digitado, esperado",
    [
        ("122,71", Decimal("122.71")),   # virgula, como se digita em portugues
        ("122.71", Decimal("122.71")),   # ponto tambem serve
        ("1", Decimal("1")),
        ("0,001", Decimal("0.001")),
        ("  45,5  ", Decimal("45.5")),   # espaco em volta nao atrapalha
    ],
)
def test_converte_o_limite_digitado(digitado, esperado):
    valor, erro = setor_service.converter_limite(digitado)

    assert erro is None
    assert valor == esperado


@pytest.mark.parametrize("vazio", ["", "   ", None])
def test_limite_vazio_e_valido_e_vira_none(vazio):
    """Regra 10: limite NULL e permitido — significa 'nao gera alerta de consumo'."""
    valor, erro = setor_service.converter_limite(vazio)

    assert valor is None
    assert erro is None


@pytest.mark.parametrize("invalido", ["0", "0,0", "-1", "-0,5"])
def test_limite_zero_ou_negativo_e_recusado(invalido):
    """Espelha ck_setor_limite_positivo: NULL ou maior que zero."""
    valor, erro = setor_service.converter_limite(invalido)

    assert valor is None
    assert "maior que zero" in erro


@pytest.mark.parametrize("invalido", ["abc", "12,34,56", "1e", "--3"])
def test_limite_que_nao_e_numero_e_recusado(invalido):
    valor, erro = setor_service.converter_limite(invalido)

    assert valor is None
    assert "número" in erro


# ---------------------------------------------------------------------------
# Validacao do formulario
# ---------------------------------------------------------------------------


def test_nome_e_obrigatorio(sem_setor_cadastrado):
    erros = setor_service.validar({"nome": "   "})

    assert erros == ["O nome do setor é obrigatório."]


def test_formulario_minimo_valido_passa(sem_setor_cadastrado):
    assert setor_service.validar({"nome": "Produção"}) == []


def test_nome_repetido_e_recusado(com_setor):
    com_setor("Produção")

    erros = setor_service.validar({"nome": "Produção"})

    assert len(erros) == 1
    assert "Já existe um setor" in erros[0]


def test_na_edicao_o_setor_nao_acusa_nome_repetido_contra_si_mesmo(com_setor):
    existente = com_setor("Produção", id_setor=3)

    erros = setor_service.validar({"nome": "Produção"}, id_existente=existente.id)

    assert erros == []


def test_nome_longo_demais_e_recusado(sem_setor_cadastrado):
    erros = setor_service.validar({"nome": "x" * 121})

    assert any("no máximo 120" in e for e in erros)


def test_descricao_longa_demais_e_recusada(sem_setor_cadastrado):
    erros = setor_service.validar({"nome": "Produção", "descricao": "x" * 256})

    assert any("no máximo 255" in e for e in erros)


def test_arquivo_de_modelo_longo_demais_e_recusado(sem_setor_cadastrado):
    erros = setor_service.validar({"nome": "Produção", "arquivo_modelo": "x" * 121})

    assert any("no máximo 120" in e for e in erros)


def test_os_erros_se_acumulam(sem_setor_cadastrado):
    """O formulario mostra tudo de uma vez, nao um erro por tentativa."""
    erros = setor_service.validar({"nome": "", "limite_consumo_kwh": "-5"})

    assert len(erros) == 2


def test_limite_invalido_aparece_junto_com_o_nome_valido(sem_setor_cadastrado):
    erros = setor_service.validar({"nome": "Utilidades", "limite_consumo_kwh": "0"})

    assert len(erros) == 1
    assert "maior que zero" in erros[0]
