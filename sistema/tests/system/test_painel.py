"""Fluxo completo do painel pelas telas (issue #20).

Exige o banco de pé:  docker compose up -d db

Os dados são semeados pelo ORM, com valores realistas da base da siderúrgica.
Nada de dado inventado na tela: o painel lê o que está no banco, e quando o banco
está vazio ele diz isso.
"""

import json
import re
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Alerta, Leitura, Medidor, Setor, StatusAlerta, TipoAlerta
from tests.conftest import SENHA_GESTOR, SENHA_OPERADOR


def entrar(cliente, email, senha):
    return cliente.post("/login", data={"email": email, "senha": senha}, follow_redirects=True)


@pytest.fixture
def cenario(sessao):
    """Dois setores, dois medidores e uma série de leituras de 15 em 15 minutos."""
    producao = Setor(
        nome="Produção", limite_consumo_kwh=Decimal("122.710"), tem_fator_potencia=True
    )
    utilidades = Setor(nome="Utilidades")
    med_prod = Medidor(setor=producao, codigo="MED-PROD")
    med_util = Medidor(setor=utilidades, codigo="MED-UTIL")
    sessao.add_all([med_prod, med_util])
    sessao.commit()

    inicio = datetime(2018, 1, 1, 0, 15)
    for i in range(8):
        sessao.add(
            Leitura(
                id_medidor=med_prod.id,
                data_hora=inicio + timedelta(minutes=15 * i),
                consumo_kwh=Decimal(f"{3 + i}.170"),
                fator_potencia=Decimal("0.950") if i % 2 == 0 else Decimal("0.910"),
            )
        )
    sessao.commit()
    return {
        "producao": producao.id,
        "utilidades": utilidades.id,
        "med_prod": med_prod.id,
        "med_util": med_util.id,
    }


@pytest.fixture
def operador(cliente, usuarios, cenario):
    entrar(cliente, "operador@gestenergia.local", SENHA_OPERADOR)
    return cliente


@pytest.fixture
def gestor(cliente, usuarios, cenario):
    entrar(cliente, "gestor@gestenergia.local", SENHA_GESTOR)
    return cliente


def dados_do_grafico(corpo: str) -> dict:
    """Lê o JSON que o template embute para o gráfico."""
    achado = re.search(
        r'<script id="dados-do-grafico" type="application/json">(.*?)</script>', corpo, re.S
    )
    assert achado, "o JSON da série não foi embutido na página"
    return json.loads(achado.group(1))


# ---------------------------------------------------------------------------
# Acesso
# ---------------------------------------------------------------------------


def test_visitante_e_mandado_para_o_login(cliente, usuarios):
    resposta = cliente.get("/painel")

    assert resposta.status_code == 302
    assert "/login" in resposta.headers["Location"]


def test_os_dois_perfis_veem_o_painel(operador):
    assert operador.get("/painel").status_code == 200


def test_o_menu_leva_ao_painel(operador):
    assert 'href="/painel"' in operador.get("/").get_data(as_text=True)


# ---------------------------------------------------------------------------
# Critério 1: gráfico com Chart.js LOCAL
# ---------------------------------------------------------------------------


def test_o_chartjs_vem_do_proprio_sistema(operador):
    corpo = operador.get("/painel").get_data(as_text=True)

    assert "/static/vendor/chart.umd.js" in corpo


def test_nenhuma_biblioteca_de_cdn_na_pagina(operador):
    """CLAUDE.md: a máquina do laboratório pode estar sem internet."""
    corpo = operador.get("/painel").get_data(as_text=True).lower()

    for proibido in ["cdn", "unpkg", "jsdelivr", "googleapis", "http://", "https://"]:
        assert proibido not in corpo, f"referência externa encontrada: {proibido}"


def test_o_arquivo_do_chartjs_e_servido(operador):
    resposta = operador.get("/static/vendor/chart.umd.js")

    assert resposta.status_code == 200
    assert len(resposta.get_data()) > 100_000


def test_a_serie_do_grafico_vem_em_ordem_cronologica(operador):
    dados = dados_do_grafico(operador.get("/painel").get_data(as_text=True))

    assert dados["rotulos"] == sorted(dados["rotulos"])
    assert dados["rotulos"][0] == "01/01 00:15"
    assert len(dados["real"]) == 8


def test_o_previsto_vem_nulo_enquanto_a_previsao_nao_existe(operador):
    """Regra 4: sem 4 leituras anteriores e sem modelo, não há previsão — e isso não é erro."""
    dados = dados_do_grafico(operador.get("/painel").get_data(as_text=True))

    assert all(valor is None for valor in dados["previsto"])
    assert dados["tem_previsto"] is False


def test_a_tela_explica_por_que_nao_ha_previsao(operador):
    corpo = operador.get("/painel").get_data(as_text=True)

    assert "4 leituras" in corpo
    assert "sem previsão ainda" in corpo


def test_a_legenda_existe_em_html_com_texto(operador):
    """Identidade nunca só por cor, e sem depender de JavaScript para existir."""
    corpo = operador.get("/painel").get_data(as_text=True)

    assert "Consumo real" in corpo
    assert "Consumo previsto" in corpo
    assert "legenda-linha" in corpo


def test_o_grafico_tem_o_par_em_tabela(operador):
    """Todo valor do gráfico alcançável sem passar o mouse."""
    corpo = operador.get("/painel").get_data(as_text=True)

    assert "Ver os mesmos dados em tabela" in corpo
    assert "3,170" in corpo


def test_a_tabela_le_do_mais_recente_para_o_mais_antigo(operador):
    corpo = operador.get("/painel").get_data(as_text=True)
    inicio_tabela = corpo.index("Ver os mesmos dados em tabela")
    trecho = corpo[inicio_tabela:]

    assert trecho.index("01/01/2018 02:00") < trecho.index("01/01/2018 00:15")


# ---------------------------------------------------------------------------
# Critério 2: alertas com cor por tipo
# ---------------------------------------------------------------------------


def test_os_dois_tipos_aparecem_nos_totais_mesmo_com_zero(operador):
    """"0 alertas de fator de potência" é informação; a linha ausente seria ambígua."""
    corpo = operador.get("/painel").get_data(as_text=True)

    assert "Consumo acima do limite" in corpo
    assert "Fator de potência baixo" in corpo


def test_sem_alerta_a_tela_explica_de_onde_eles_vem(operador):
    corpo = operador.get("/painel").get_data(as_text=True)

    assert "Nenhum alerta aberto." in corpo
    assert "regra 2" in corpo


def test_o_alerta_aberto_aparece_com_cor_e_rotulo(operador, cenario, sessao):
    leitura = sessao.scalar(select(Leitura).order_by(Leitura.data_hora))
    sessao.add(
        Alerta(
            id_leitura=leitura.id,
            tipo=TipoAlerta.CONSUMO_ACIMA_LIMITE,
            valor_observado=Decimal("150.000"),
            limite_referencia=Decimal("122.710"),
        )
    )
    sessao.commit()

    corpo = operador.get("/painel").get_data(as_text=True)

    assert "Consumo acima do limite" in corpo
    assert "marca-de-tipo" in corpo
    assert "150,000" in corpo
    assert "122,710" in corpo


def test_cada_tipo_tem_a_sua_cor(operador, cenario, sessao):
    leituras = list(sessao.scalars(select(Leitura).order_by(Leitura.data_hora).limit(2)))
    sessao.add_all(
        [
            Alerta(
                id_leitura=leituras[0].id,
                tipo=TipoAlerta.CONSUMO_ACIMA_LIMITE,
                valor_observado=Decimal("150"),
                limite_referencia=Decimal("122.710"),
            ),
            Alerta(
                id_leitura=leituras[1].id,
                tipo=TipoAlerta.FATOR_POTENCIA_BAIXO,
                valor_observado=Decimal("0.910"),
                limite_referencia=Decimal("0.920"),
            ),
        ]
    )
    sessao.commit()

    corpo = operador.get("/painel").get_data(as_text=True)

    from app.services import painel_service

    assert painel_service.CORES_POR_TIPO_DE_ALERTA[TipoAlerta.CONSUMO_ACIMA_LIMITE] in corpo
    assert painel_service.CORES_POR_TIPO_DE_ALERTA[TipoAlerta.FATOR_POTENCIA_BAIXO] in corpo


def test_alerta_resolvido_nao_aparece_na_lista_de_abertos(operador, cenario, sessao, usuarios):
    leitura = sessao.scalar(select(Leitura).order_by(Leitura.data_hora))
    sessao.add(
        Alerta(
            id_leitura=leitura.id,
            tipo=TipoAlerta.CONSUMO_ACIMA_LIMITE,
            valor_observado=Decimal("150"),
            limite_referencia=Decimal("122.710"),
            status=StatusAlerta.RESOLVIDO,
            resolvido_em=datetime(2018, 1, 2, 10, 0),
            usuario_resolucao=usuarios["gestor"],
            # Issue #28: o CHECK exige a observacao quando o alerta e RESOLVIDO.
            observacao_resolucao="Carga remanejada para o turno da noite",
        )
    )
    sessao.commit()

    corpo = operador.get("/painel").get_data(as_text=True)

    assert "Nenhum alerta aberto." in corpo


# ---------------------------------------------------------------------------
# Critério 3: filtro por setor
# ---------------------------------------------------------------------------


def test_o_filtro_de_setor_lista_todos_os_setores(operador):
    corpo = operador.get("/painel").get_data(as_text=True)

    assert "Todos os setores" in corpo
    assert "Produção" in corpo
    assert "Utilidades" in corpo


def test_o_filtro_de_setor_limita_os_medidores(operador, cenario):
    corpo = operador.get(f"/painel?setor={cenario['utilidades']}").get_data(as_text=True)

    assert "MED-UTIL" in corpo
    assert "MED-PROD" not in corpo


def test_o_setor_escolhido_muda_o_grafico(operador, cenario):
    """O medidor de Utilidades não tem leitura: o painel diz isso em vez de quebrar."""
    corpo = operador.get(f"/painel?setor={cenario['utilidades']}").get_data(as_text=True)

    assert "ainda não tem leitura" in corpo


def test_o_filtro_escopa_os_alertas_tambem(operador, cenario, sessao):
    """Os filtros valem para tudo abaixo deles: gráfico, tabela e alertas."""
    leitura = sessao.scalar(select(Leitura).order_by(Leitura.data_hora))
    sessao.add(
        Alerta(
            id_leitura=leitura.id,
            tipo=TipoAlerta.CONSUMO_ACIMA_LIMITE,
            valor_observado=Decimal("150"),
            limite_referencia=Decimal("122.710"),
        )
    )
    sessao.commit()

    # O alerta é da Produção: aparece nela e não em Utilidades.
    com_producao = operador.get(f"/painel?setor={cenario['producao']}").get_data(as_text=True)
    com_utilidades = operador.get(f"/painel?setor={cenario['utilidades']}").get_data(as_text=True)

    assert "150,000" in com_producao
    assert "Nenhum alerta aberto." in com_utilidades


def test_o_painel_abre_no_medidor_que_tem_dado(operador, cenario):
    """Produção vem depois de Utilidades? Não importa: abre em quem tem leitura.

    Sem isso o painel abria no primeiro medidor em ordem alfabética, que pode
    estar vazio — gráfico em branco tendo dado no medidor ao lado.
    """
    corpo = operador.get("/painel").get_data(as_text=True)

    assert "ainda não tem leitura" not in corpo
    assert "MED-PROD" in corpo
    assert len(dados_do_grafico(corpo)["real"]) == 8


def test_o_filtro_de_medidor_troca_a_serie(operador, cenario):
    corpo = operador.get(f"/painel?medidor={cenario['med_util']}").get_data(as_text=True)

    assert "MED-UTIL" in corpo
    assert "ainda não tem leitura" in corpo


@pytest.mark.parametrize("janela, esperado", [("dia", 8), ("semana", 8), ("mes", 8)])
def test_a_janela_nao_quebra_com_poucas_leituras(operador, janela, esperado):
    """Janela maior que o histórico devolve o histórico, não erro."""
    dados = dados_do_grafico(operador.get(f"/painel?janela={janela}").get_data(as_text=True))

    assert len(dados["real"]) == esperado


def test_janela_invalida_na_query_string_nao_quebra(operador):
    resposta = operador.get("/painel?janela=xpto")

    assert resposta.status_code == 200


def test_setor_invalido_na_query_string_nao_quebra(operador):
    for valor in ["abc", "9999", ""]:
        assert operador.get(f"/painel?setor={valor}").status_code == 200


def test_medidor_invalido_na_query_string_nao_quebra(operador):
    assert operador.get("/painel?medidor=9999").status_code == 200


def test_a_tela_explica_que_o_periodo_conta_leituras(operador):
    """As bases são de 2018 e 2014: uma janela contada de hoje viria vazia."""
    corpo = operador.get("/painel").get_data(as_text=True)

    assert "conta <strong>leituras</strong>" in corpo


# ---------------------------------------------------------------------------
# Painel sem dado nenhum
# ---------------------------------------------------------------------------


def test_painel_sem_medidor_nenhum_explica_o_que_fazer(cliente, usuarios, banco):
    """É o estado de quem acabou de rodar o banco.sql: nada de mockup na tela."""
    entrar(cliente, "gestor@gestenergia.local", SENHA_GESTOR)

    corpo = cliente.get("/painel").get_data(as_text=True)

    assert "Nenhum medidor para mostrar." in corpo
    assert "Nenhum alerta aberto." in corpo
    # Sem dado, o Chart.js nem é carregado.
    assert "/static/vendor/chart.umd.js" not in corpo
