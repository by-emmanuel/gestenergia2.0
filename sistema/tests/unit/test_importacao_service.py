"""Testes da importação de CSV sem banco (issue #19).

A detecção de formato e as conversões são puras e são testadas direto. O que
toca no banco está em `tests/system/test_importacao.py`.

As três armadilhas desta importação têm teste cada uma: a siderúrgica fora de
ordem cronológica, o fator de potência em percentual (regra 6) e os dois
formatos de data convivendo.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from app.services import importacao_service as importacao

CABECALHO_SIDERURGICA = (
    "date,Usage_kWh,Lagging_Current_Reactive.Power_kVarh,"
    "Leading_Current_Reactive_Power_kVarh,CO2(tCO2),Lagging_Current_Power_Factor,"
    "Leading_Current_Power_Factor,NSM,WeekStatus,Day_of_week,Load_Type"
)
CABECALHO_SETOR = "date,Usage_kWh"


# ---------------------------------------------------------------------------
# Detecção do formato — critério da #19: sem o usuário escolher
# ---------------------------------------------------------------------------


def test_reconhece_a_siderurgica_pelo_fator_de_potencia():
    assert importacao.detectar_formato(CABECALHO_SIDERURGICA.split(",")) == "siderurgica"


def test_reconhece_o_arquivo_de_setor():
    assert importacao.detectar_formato(["date", "Usage_kWh"]) == "setor"


@pytest.mark.parametrize(
    "colunas",
    [
        [],
        None,
        ["data", "consumo"],          # em português, não é o formato das bases
        ["date"],                     # falta o consumo
        ["Usage_kWh"],                # falta a data
        ["date", "kWh"],
    ],
)
def test_cabecalho_desconhecido_devolve_none(colunas):
    assert importacao.detectar_formato(colunas) is None


def test_espacos_no_cabecalho_nao_atrapalham():
    assert importacao.detectar_formato([" date ", " Usage_kWh "]) == "setor"


# ---------------------------------------------------------------------------
# Regra 6 — o fator vem em percentual e é guardado de 0 a 1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bruto, esperado",
    [
        ("73.21", Decimal("0.732")),
        ("100", Decimal("1.000")),
        ("0", Decimal("0.000")),
        ("92", Decimal("0.920")),
        ("73,21", Decimal("0.732")),  # decimal com vírgula também
    ],
)
def test_converte_o_fator_do_percentual(bruto, esperado):
    assert importacao.converter_fator_do_percentual(bruto) == esperado


@pytest.mark.parametrize("bruto", ["", None, "   ", "abc", "-1", "101", "1000"])
def test_fator_vazio_ou_fora_da_faixa_vira_none(bruto):
    """A coluna tem CHECK de 0 a 1: uma linha estranha não pode derrubar tudo."""
    assert importacao.converter_fator_do_percentual(bruto) is None


def test_o_fator_92_por_cento_vira_exatamente_092():
    """Regra 1: o valor de borda precisa chegar exato, senão 0,92 geraria alerta."""
    assert importacao.converter_fator_do_percentual("92") == Decimal("0.92")


# ---------------------------------------------------------------------------
# Os dois formatos de data
# ---------------------------------------------------------------------------


def test_data_da_siderurgica_e_dia_primeiro():
    """01/02/2018 é 1º de fevereiro, não 2 de janeiro."""
    assert importacao.converter_data("01/02/2018 00:15", "siderurgica") == datetime(
        2018, 2, 1, 0, 15
    )


def test_data_do_setor_e_iso():
    assert importacao.converter_data("2014-02-01 00:15:00", "setor") == datetime(2014, 2, 1, 0, 15)


def test_data_no_formato_errado_devolve_none():
    """O leitor de cada base não aceita o formato da outra, de propósito."""
    assert importacao.converter_data("2014-02-01 00:15:00", "siderurgica") is None
    assert importacao.converter_data("01/02/2018 00:15", "setor") is None


# ---------------------------------------------------------------------------
# Leitura das linhas — ordenação e linhas inválidas
# ---------------------------------------------------------------------------


def linhas_lidas(conteudo, formato):
    resultado = importacao.Resultado()
    return importacao._ler_linhas(conteudo, formato, resultado), resultado


def test_ordena_a_siderurgica_que_vem_fora_de_ordem():
    """Armadilha da seção 2.2: a linha das 00:00 vem no FIM de cada dia.

    Importar na ordem do arquivo corromperia os lags de toda a primeira leitura
    de cada dia — 729 vezes no ano.
    """
    conteudo = "\n".join([
        CABECALHO_SIDERURGICA,
        "01/01/2018 00:15,3.17,2.95,0,0,73.21,100,900,Weekday,Monday,Light_Load",
        "01/01/2018 00:30,4.00,4.46,0,0,66.77,100,1800,Weekday,Monday,Light_Load",
        "01/01/2018 00:00,5.00,1.00,0,0,80.00,100,0,Weekday,Monday,Light_Load",
    ])

    linhas, _ = linhas_lidas(conteudo, "siderurgica")

    assert [l["data_hora"].strftime("%H:%M") for l in linhas] == ["00:00", "00:15", "00:30"]


def test_conta_as_linhas_invalidas_por_motivo():
    conteudo = "\n".join([
        CABECALHO_SETOR,
        "2014-01-01 00:00:00,9.95",
        "data-ruim,10.00",
        "2014-01-01 00:30:00,nao-e-numero",
        "2014-01-01 00:45:00,-5",       # consumo negativo
        "2014-01-01 01:00:00,11.40",
    ])

    linhas, resultado = linhas_lidas(conteudo, "setor")

    assert len(linhas) == 2
    assert resultado.ignoradas == 3
    assert resultado.motivos == {"data e hora inválidas": 1, "consumo inválido": 2}


def test_o_fator_so_e_lido_no_formato_da_siderurgica():
    conteudo = f"{CABECALHO_SETOR}\n2014-01-01 00:00:00,9.95"

    linhas, _ = linhas_lidas(conteudo, "setor")

    assert linhas[0]["fator_potencia"] is None


def test_o_fator_da_siderurgica_chega_convertido():
    conteudo = "\n".join([
        CABECALHO_SIDERURGICA,
        "01/01/2018 00:15,3.17,2.95,0,0,73.21,100,900,Weekday,Monday,Light_Load",
    ])

    linhas, _ = linhas_lidas(conteudo, "siderurgica")

    assert linhas[0]["fator_potencia"] == Decimal("0.732")
    assert linhas[0]["consumo_kwh"] == Decimal("3.17")


# ---------------------------------------------------------------------------
# Erros que nem chegam a ler o arquivo
# ---------------------------------------------------------------------------


def test_sem_medidor_recusa_com_mensagem():
    resultado = importacao.importar(None, f"{CABECALHO_SETOR}\n2014-01-01 00:00:00,9.95")

    assert not resultado.deu_certo
    assert "Escolha o medidor" in resultado.erros[0]


def test_formato_desconhecido_recusa_com_mensagem():
    from app.models import Medidor, Setor

    medidor = Medidor(id=1, codigo="MED-X", id_setor=1, ativo=True)
    medidor.setor = Setor(id=1, nome="Produção", ativo=True)

    resultado = importacao.importar(medidor, "data;consumo\n01/01/2018;3,17")

    assert not resultado.deu_certo
    assert "Não reconheci o formato" in resultado.erros[0]
    assert resultado.formato is None


def test_medidor_desativado_recusa_com_mensagem():
    from app.models import Medidor, Setor

    medidor = Medidor(id=1, codigo="MED-X", id_setor=1, ativo=False)
    medidor.setor = Setor(id=1, nome="Produção", ativo=True)

    resultado = importacao.importar(medidor, f"{CABECALHO_SETOR}\n2014-01-01 00:00:00,9.95")

    assert not resultado.deu_certo
    assert "desativado" in resultado.erros[0]
