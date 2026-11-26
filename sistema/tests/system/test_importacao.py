"""Fluxo completo da importação de CSV pelas telas (issue #19).

Exige o banco de pé:  docker compose up -d db

Regra 7: importar leitura é atividade do OPERADOR, então a tela vale para os
dois perfis.
"""

import io
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Alerta, Leitura, Medidor, Setor, TipoAlerta
from app.services import previsao_service
from tests.conftest import SENHA_GESTOR, SENHA_OPERADOR

CABECALHO_SIDERURGICA = (
    "date,Usage_kWh,Lagging_Current_Reactive.Power_kVarh,"
    "Leading_Current_Reactive_Power_kVarh,CO2(tCO2),Lagging_Current_Power_Factor,"
    "Leading_Current_Power_Factor,NSM,WeekStatus,Day_of_week,Load_Type"
)
MODELO_DA_PRODUCAO = "modelo_consumo_producao.pkl"


@pytest.fixture(autouse=True)
def modelos_de_verdade(app):
    previsao_service.carregar_modelos(app.config["CAMINHO_MODELO"])


@pytest.fixture
def medidor(sessao):
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
def operador(cliente, usuarios, medidor):
    cliente.post(
        "/login",
        data={"email": "operador@gestenergia.local", "senha": SENHA_OPERADOR},
        follow_redirects=True,
    )
    return cliente


def csv_de_setor(quantidade=10, inicio=0, consumo=10.0):
    """CSV no formato de data/setores/: date em ISO, sem fator."""
    linhas = ["date,Usage_kWh"]
    for passo in range(quantidade):
        minuto = (inicio + passo) * 15
        hora, minuto = divmod(minuto, 60)
        linhas.append(f"2014-01-01 {hora:02d}:{minuto:02d}:00,{consumo + passo:.4f}")
    return "\n".join(linhas)


def enviar(cliente, id_medidor, conteudo, nome="leituras.csv"):
    return cliente.post(
        "/leituras/importar",
        data={
            "id_medidor": str(id_medidor),
            "arquivo": (io.BytesIO(conteudo.encode("utf-8")), nome),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )


def leituras_de(sessao):
    return list(sessao.scalars(select(Leitura).order_by(Leitura.data_hora)))


def alertas_de(sessao):
    return list(sessao.scalars(select(Alerta)))


# ---------------------------------------------------------------------------
# Acesso
# ---------------------------------------------------------------------------


def test_visitante_e_mandado_para_o_login(cliente, usuarios):
    resposta = cliente.get("/leituras/importar")

    assert resposta.status_code == 302
    assert "/login" in resposta.headers["Location"]


def test_o_gestor_tambem_importa(cliente, usuarios, medidor, sessao, recarregar):
    """Regra 7: o gestor faz tudo o que o operador faz."""
    cliente.post(
        "/login",
        data={"email": "gestor@gestenergia.local", "senha": SENHA_GESTOR},
        follow_redirects=True,
    )

    assert enviar(cliente, medidor, csv_de_setor()).status_code == 200
    recarregar()
    assert len(leituras_de(sessao)) == 10


# ---------------------------------------------------------------------------
# O caminho feliz
# ---------------------------------------------------------------------------


def test_importa_o_formato_de_setor(operador, medidor, sessao, recarregar):
    resposta = enviar(operador, medidor, csv_de_setor(quantidade=10))

    assert resposta.status_code == 200
    corpo = resposta.get_data(as_text=True)
    assert "10" in corpo and "importada" in corpo
    recarregar()
    assert len(leituras_de(sessao)) == 10


def test_importa_o_formato_da_siderurgica_e_converte_o_fator(
    operador, medidor, sessao, recarregar
):
    """Regra 6: 73,21% vira 0,732 no banco."""
    conteudo = "\n".join([
        CABECALHO_SIDERURGICA,
        "01/01/2018 00:15,3.17,2.95,0,0,73.21,100,900,Weekday,Monday,Light_Load",
        "01/01/2018 00:30,4.00,4.46,0,0,66.77,100,1800,Weekday,Monday,Light_Load",
    ])

    enviar(operador, medidor, conteudo)
    recarregar()

    leituras = leituras_de(sessao)
    assert [l.fator_potencia for l in leituras] == [Decimal("0.732"), Decimal("0.668")]
    assert leituras[0].consumo_kwh == Decimal("3.170")


def test_a_quinta_leitura_em_diante_vem_com_previsao(operador, medidor, sessao, recarregar):
    """Regra 4 valendo igual na importação: as 4 primeiras ficam sem."""
    enviar(operador, medidor, csv_de_setor(quantidade=10))
    recarregar()

    previstos = [l.consumo_previsto_kwh for l in leituras_de(sessao)]
    assert previstos[:4] == [None] * 4
    assert all(p is not None for p in previstos[4:])


def test_a_segunda_importacao_continua_de_onde_a_primeira_parou(
    operador, medidor, sessao, recarregar
):
    """As leituras já no banco servem de lag para o começo do arquivo seguinte."""
    enviar(operador, medidor, csv_de_setor(quantidade=8, inicio=0))
    enviar(operador, medidor, csv_de_setor(quantidade=8, inicio=8))
    recarregar()

    leituras = leituras_de(sessao)
    assert len(leituras) == 16
    # Nenhuma do segundo arquivo pode ficar sem previsão: havia 8 antes dela.
    assert all(l.consumo_previsto_kwh is not None for l in leituras[8:])


def test_a_importacao_abre_alertas(operador, medidor, sessao, recarregar):
    """Critério da #27: a importação também gera previsões e alertas."""
    conteudo = "\n".join([
        CABECALHO_SIDERURGICA,
        *[
            f"01/01/2018 0{h}:00,10.00,2.95,0,0,70.00,100,900,Weekday,Monday,Light_Load"
            for h in range(1, 6)
        ],
    ])

    enviar(operador, medidor, conteudo)
    recarregar()

    alertas = alertas_de(sessao)
    assert len(alertas) == 5
    assert {a.tipo for a in alertas} == {TipoAlerta.FATOR_POTENCIA_BAIXO}


# ---------------------------------------------------------------------------
# Regra 3 — duplicadas
# ---------------------------------------------------------------------------


def test_linha_repetida_no_proprio_arquivo_e_pulada(operador, medidor, sessao, recarregar):
    conteudo = "\n".join([
        "date,Usage_kWh",
        "2014-01-01 00:00:00,10.0",
        "2014-01-01 00:00:00,11.0",
        "2014-01-01 00:15:00,12.0",
    ])

    resposta = enviar(operador, medidor, conteudo)
    recarregar()

    assert len(leituras_de(sessao)) == 2
    assert "repetida dentro do próprio arquivo" in resposta.get_data(as_text=True)


def test_importar_o_mesmo_arquivo_duas_vezes_nao_duplica(operador, medidor, sessao, recarregar):
    """Regra 3: a segunda importação não acrescenta nada e diz por quê."""
    enviar(operador, medidor, csv_de_setor(quantidade=5))
    resposta = enviar(operador, medidor, csv_de_setor(quantidade=5))
    recarregar()

    assert len(leituras_de(sessao)) == 5
    assert "já existe uma leitura" in resposta.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Erros
# ---------------------------------------------------------------------------


def test_sem_arquivo_avisa(operador, medidor):
    resposta = operador.post(
        "/leituras/importar",
        data={"id_medidor": str(medidor)},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert resposta.status_code == 400
    assert "Escolha o arquivo CSV" in resposta.get_data(as_text=True)


def test_formato_desconhecido_avisa_e_nao_grava(operador, medidor, sessao, recarregar):
    resposta = enviar(operador, medidor, "data;consumo\n01/01/2018;3,17")

    assert resposta.status_code == 400
    assert "Não reconheci o formato" in resposta.get_data(as_text=True)
    recarregar()
    assert leituras_de(sessao) == []


def test_arquivo_com_bom_e_lido(operador, medidor, sessao, recarregar):
    """O CSV da siderúrgica vem COM BOM: sem utf-8-sig o cabeçalho não casaria."""
    conteudo = "﻿" + csv_de_setor(quantidade=3)

    enviar(operador, medidor, conteudo)
    recarregar()

    assert len(leituras_de(sessao)) == 3


def test_a_tela_lista_os_medidores(operador, medidor):
    corpo = operador.get("/leituras/importar").get_data(as_text=True)

    assert "MED-PROD" in corpo
    assert "Importar" in corpo
