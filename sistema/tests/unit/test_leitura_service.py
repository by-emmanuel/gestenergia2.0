"""Testes das regras de leitura sem banco (issue #18).

As conversões são puras e são testadas direto. A validação consulta os
repositórios, então eles são trocados por dublês.

Casos de borda obrigatórios pelo CLAUDE.md: fator 0,91 / 0,92 / 0,93 e leitura
duplicada. Os de consumo igual e acima do limite, e os de menos de 4 leituras,
entram com o AlertaService (#27) e o PrevisaoService (#26).
"""

from datetime import datetime
from decimal import Decimal

import pytest

from app.models import Medidor, Setor
from app.services import leitura_service


@pytest.fixture
def mundo(monkeypatch):
    """Monta o cenário: que medidor existe e se já há leitura naquele instante."""

    def configurar(medidor=None, duplicada=False, anteriores=0):
        monkeypatch.setattr(
            leitura_service.medidor_repository, "buscar_por_id", lambda i: medidor
        )
        monkeypatch.setattr(
            leitura_service.leitura_repository, "existe", lambda m, d: duplicada
        )
        monkeypatch.setattr(
            leitura_service.leitura_repository,
            "ultimas_do_medidor",
            lambda m, q: [object()] * min(anteriores, q),
        )

    return configurar


def medidor_ativo(ativo=True):
    medidor = Medidor(id=1, codigo="MED-PROD", id_setor=1, ativo=ativo)
    medidor.setor = Setor(id=1, nome="Produção", ativo=True)
    return medidor


FORMULARIO = {
    "id_medidor": "1",
    "data_hora": "2018-01-01T00:15",
    "consumo_kwh": "3,17",
    "fator_potencia": "0,95",
}


# ---------------------------------------------------------------------------
# Data e hora
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "digitado",
    ["2018-01-01T00:15", "2018-01-01 00:15", "2018-01-01T00:15:00", "2018-01-01 00:15:00"],
)
def test_aceita_os_formatos_de_data_hora(digitado):
    valor, erro = leitura_service.converter_data_hora(digitado)

    assert erro is None
    assert valor == datetime(2018, 1, 1, 0, 15)


def test_os_microssegundos_sao_zerados():
    """A coluna é DATETIME sem fração de segundo; sem zerar, a regra 3 falharia."""
    valor, _ = leitura_service.converter_data_hora("2018-01-01T00:15:00")

    assert valor.microsecond == 0


@pytest.mark.parametrize("vazio", ["", "   ", None])
def test_data_hora_e_obrigatoria(vazio):
    valor, erro = leitura_service.converter_data_hora(vazio)

    assert valor is None
    assert erro == "Informe a data e a hora da leitura."


@pytest.mark.parametrize("invalido", ["01/01/2018", "ontem", "2018-13-45T00:00", "2018-01-01"])
def test_data_hora_invalida_e_recusada(invalido):
    valor, erro = leitura_service.converter_data_hora(invalido)

    assert valor is None
    assert "inválidas" in erro


# ---------------------------------------------------------------------------
# Consumo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "digitado, esperado",
    [("3,17", Decimal("3.17")), ("3.17", Decimal("3.17")), ("0", Decimal("0")), (" 150 ", Decimal("150"))],
)
def test_converte_o_consumo(digitado, esperado):
    valor, erro = leitura_service.converter_consumo(digitado)

    assert erro is None
    assert valor == esperado


def test_consumo_zero_e_valido():
    """Planta parada registra zero: é dado legítimo, não erro."""
    valor, erro = leitura_service.converter_consumo("0")

    assert erro is None
    assert valor == Decimal("0")


@pytest.mark.parametrize("vazio", ["", "  ", None])
def test_consumo_e_obrigatorio(vazio):
    valor, erro = leitura_service.converter_consumo(vazio)

    assert valor is None
    assert erro == "Informe o consumo em kWh."


def test_consumo_negativo_e_recusado():
    """Espelha ck_leitura_consumo_nao_negativo."""
    valor, erro = leitura_service.converter_consumo("-1")

    assert valor is None
    assert "não pode ser negativo" in erro


def test_consumo_que_nao_e_numero_e_recusado():
    valor, erro = leitura_service.converter_consumo("muito")

    assert valor is None
    assert "número" in erro


# ---------------------------------------------------------------------------
# Fator de potência: regra 6 (0 a 1) e os casos de borda da regra 1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "digitado, esperado",
    [
        ("0,91", Decimal("0.91")),   # abaixo do mínimo: gera alerta (#27)
        ("0,92", Decimal("0.92")),   # exatamente o mínimo: NÃO gera alerta
        ("0,93", Decimal("0.93")),   # acima: não gera
        ("0", Decimal("0")),
        ("1", Decimal("1")),
        ("0.7321", Decimal("0.7321")),
    ],
)
def test_aceita_fator_entre_0_e_1(digitado, esperado):
    """Critério da issue: fator de potência aceito entre 0 e 1."""
    valor, erro = leitura_service.converter_fator_potencia(digitado)

    assert erro is None
    assert valor == esperado


@pytest.mark.parametrize("vazio", ["", "   ", None])
def test_fator_vazio_e_valido_e_vira_none(vazio):
    """Regra 1: hoje só a Produção tem o dado; sem ele não gera alerta nem erro."""
    valor, erro = leitura_service.converter_fator_potencia(vazio)

    assert valor is None
    assert erro is None


@pytest.mark.parametrize("acima", ["1,01", "73,21", "100"])
def test_fator_acima_de_1_e_recusado(acima):
    """Regra 6: na base vem em percentual; aqui é de 0 a 1."""
    valor, erro = leitura_service.converter_fator_potencia(acima)

    assert valor is None
    assert "de 0 a 1" in erro


def test_o_erro_do_fator_sugere_o_valor_convertido():
    """Quem digita 73,21 quer dizer 0,7321 — a mensagem diz isso."""
    _, erro = leitura_service.converter_fator_potencia("73,21")

    assert "0,7321" in erro
    # E não estraga a pontuação da frase.
    assert "percentual." in erro


def test_fator_negativo_e_recusado():
    valor, erro = leitura_service.converter_fator_potencia("-0,5")

    assert valor is None
    assert "não pode ser negativo" in erro


def test_fator_que_nao_e_numero_e_recusado():
    valor, erro = leitura_service.converter_fator_potencia("alto")

    assert valor is None
    assert "número" in erro


# ---------------------------------------------------------------------------
# Validação completa, inclusive a regra 3
# ---------------------------------------------------------------------------


def test_formulario_valido_passa(mundo):
    mundo(medidor=medidor_ativo())

    _, erros = leitura_service.validar(FORMULARIO)

    assert erros == []


def test_leitura_duplicada_e_recusada_com_mensagem_clara(mundo):
    """Regra 3, critério da issue: mesmo medidor + mesma data_hora."""
    mundo(medidor=medidor_ativo(), duplicada=True)

    _, erros = leitura_service.validar(FORMULARIO)

    assert len(erros) == 1
    assert "01/01/2018 às 00:15" in erros[0]
    assert "uma única leitura por data e hora" in erros[0]


def test_medidor_e_obrigatorio(mundo):
    mundo(medidor=medidor_ativo())

    _, erros = leitura_service.validar({**FORMULARIO, "id_medidor": ""})

    assert "Escolha o medidor." in erros


def test_medidor_que_nao_existe_e_recusado(mundo):
    mundo(medidor=None)

    _, erros = leitura_service.validar(FORMULARIO)

    assert "Medidor não encontrado." in erros


def test_medidor_invalido_e_recusado(mundo):
    mundo(medidor=medidor_ativo())

    _, erros = leitura_service.validar({**FORMULARIO, "id_medidor": "abc"})

    assert "Medidor inválido." in erros


def test_medidor_desativado_nao_aceita_leitura(mundo):
    mundo(medidor=medidor_ativo(ativo=False))

    _, erros = leitura_service.validar(FORMULARIO)

    assert any("está desativado" in e for e in erros)


def test_os_erros_se_acumulam(mundo):
    mundo(medidor=medidor_ativo())

    _, erros = leitura_service.validar(
        {"id_medidor": "", "data_hora": "", "consumo_kwh": "", "fator_potencia": "9"}
    )

    assert len(erros) == 4


def test_a_duplicidade_nao_e_conferida_sem_medidor_e_data_validos(mundo):
    """Sem os dois não há o que comparar; o erro é do campo, não da regra 3."""
    mundo(medidor=medidor_ativo(), duplicada=True)

    _, erros = leitura_service.validar({**FORMULARIO, "data_hora": "invalida"})

    assert not any("uma única leitura" in e for e in erros)


# ---------------------------------------------------------------------------
# Regra 4: quantas leituras anteriores existem
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("anteriores, esperado", [(0, False), (3, False), (4, True), (10, True)])
def test_diz_se_ja_da_para_prever(mundo, anteriores, esperado):
    """Regra 4: a previsão precisa de 4 leituras anteriores do mesmo medidor."""
    mundo(medidor=medidor_ativo(), anteriores=anteriores)

    assert leitura_service.tem_leituras_para_prever(1) is esperado


def test_a_constante_da_regra_4_e_quatro():
    assert leitura_service.LEITURAS_NECESSARIAS_PARA_PREVER == 4


# ---------------------------------------------------------------------------
# Regra 1: os casos de borda de 0,92 — obrigatórios pelo CLAUDE.md
# ---------------------------------------------------------------------------


def leitura_com_fator(fator):
    from app.models import Leitura

    return Leitura(id=1, id_medidor=1, data_hora=datetime(2018, 1, 1), consumo_kwh=Decimal("10"),
                   fator_potencia=fator)


@pytest.mark.parametrize(
    "fator, abaixo",
    [
        (Decimal("0.910"), True),    # abaixo: viola
        (Decimal("0.919"), True),
        (Decimal("0.920"), False),   # EXATAMENTE o mínimo: NÃO viola
        (Decimal("0.921"), False),
        (Decimal("0.930"), False),
        (Decimal("0.000"), True),
        (Decimal("1.000"), False),
    ],
)
def test_os_casos_de_borda_do_fator_minimo(fator, abaixo):
    assert leitura_service.fator_abaixo_do_minimo(leitura_com_fator(fator)) is abaixo


def test_leitura_sem_fator_nao_e_violacao_e_nao_da_erro():
    """Regra 1: fator NULL não gera alerta e não dá erro."""
    assert leitura_service.fator_abaixo_do_minimo(leitura_com_fator(None)) is False


def test_o_minimo_e_decimal_e_nao_float():
    """Comparar Decimal com float marca exatamente 0,92 como violação.

    O float 0.92 vale 0.92000000000000004 em binário, então
    Decimal("0.920") < 0.92 é True — e seria um alerta indevido. Este teste
    trava a armadilha: foi exatamente o defeito que a suíte pegou na #18.
    """
    assert isinstance(leitura_service.FATOR_POTENCIA_MINIMO, Decimal)
    assert leitura_service.FATOR_POTENCIA_MINIMO == Decimal("0.92")

    # A prova da armadilha, deixada explícita para o motivo não se perder:
    assert Decimal("0.920") < 0.92, "contra float, 0,92 seria violação (errado)"
    assert not (Decimal("0.920") < Decimal("0.92")), "contra Decimal, 0,92 não é violação"
    assert not (Decimal("0.920") < leitura_service.FATOR_POTENCIA_MINIMO)
