"""Fluxo completo da tela de alertas (issue #28).

Exige o banco de pé:  docker compose up -d db

Regra 7: **ver** alerta é dos dois perfis — o operador precisa saber o que está
aberto no chão de fábrica. **Resolver** é só do GESTOR.
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import (
    Alerta,
    Leitura,
    Medidor,
    Setor,
    StatusAlerta,
    TipoAlerta,
)
from tests.conftest import SENHA_GESTOR, SENHA_OPERADOR

PRIMEIRA = datetime(2018, 1, 1, 0, 0)


@pytest.fixture
def cenario(sessao):
    """Dois setores, dois medidores e alertas dos dois tipos."""
    producao = Setor(nome="Produção", tem_fator_potencia=True,
                     limite_consumo_kwh=Decimal("122.980"))
    utilidades = Setor(nome="Utilidades", limite_consumo_kwh=Decimal("11.959"))
    med_prod = Medidor(setor=producao, codigo="MED-PROD")
    med_util = Medidor(setor=utilidades, codigo="MED-UTIL")
    sessao.add_all([med_prod, med_util])
    sessao.commit()

    alertas = []
    for passo in range(5):
        leitura = Leitura(
            id_medidor=med_prod.id,
            data_hora=PRIMEIRA + timedelta(minutes=15 * passo),
            consumo_kwh=Decimal("10.000"),
            fator_potencia=Decimal("0.730"),
        )
        sessao.add(leitura)
        sessao.flush()
        alertas.append(Alerta(
            id_leitura=leitura.id,
            tipo=TipoAlerta.FATOR_POTENCIA_BAIXO,
            valor_observado=Decimal("0.730"),
            limite_referencia=Decimal("0.920"),
            mensagem="Fator de potência baixo",
        ))

    leitura = Leitura(
        id_medidor=med_util.id,
        data_hora=PRIMEIRA,
        consumo_kwh=Decimal("13.000"),
        consumo_previsto_kwh=Decimal("12.500"),
    )
    sessao.add(leitura)
    sessao.flush()
    alertas.append(Alerta(
        id_leitura=leitura.id,
        tipo=TipoAlerta.CONSUMO_ACIMA_LIMITE,
        valor_observado=Decimal("12.500"),
        limite_referencia=Decimal("11.959"),
        mensagem="Consumo acima do limite",
    ))

    sessao.add_all(alertas)
    sessao.commit()
    return {"producao": producao.id, "utilidades": utilidades.id,
            "alertas": [a.id for a in alertas]}


def entrar(cliente, email, senha):
    return cliente.post("/login", data={"email": email, "senha": senha}, follow_redirects=True)


@pytest.fixture
def gestor(cliente, usuarios, cenario):
    entrar(cliente, "gestor@gestenergia.local", SENHA_GESTOR)
    return cliente


@pytest.fixture
def operador(cliente, usuarios, cenario):
    entrar(cliente, "operador@gestenergia.local", SENHA_OPERADOR)
    return cliente


def alertas_de(sessao):
    return list(sessao.scalars(select(Alerta).order_by(Alerta.id)))


# ---------------------------------------------------------------------------
# Acesso — regra 7
# ---------------------------------------------------------------------------


def test_visitante_e_mandado_para_o_login(cliente, usuarios):
    resposta = cliente.get("/alertas/")

    assert resposta.status_code == 302
    assert "/login" in resposta.headers["Location"]


def test_o_operador_ve_a_lista(operador):
    """Ver é dos dois perfis: o operador precisa saber o que está aberto."""
    resposta = operador.get("/alertas/")

    assert resposta.status_code == 200
    assert "Fator de potência baixo" in resposta.get_data(as_text=True)


def test_o_operador_nao_ve_o_formulario_de_resolver(operador):
    corpo = operador.get("/alertas/").get_data(as_text=True)

    assert "Marcar como resolvido" not in corpo
    assert "Só o gestor resolve" in corpo


def test_o_operador_nao_consegue_resolver_pela_rota(operador, cenario, sessao, recarregar):
    """Esconder o botão não basta: a rota tem de recusar."""
    resposta = operador.post(
        f"/alertas/{cenario['alertas'][0]}/resolver",
        data={"observacao": "Tentando pelo POST direto"},
    )

    assert resposta.status_code == 403
    recarregar()
    assert alertas_de(sessao)[0].status == StatusAlerta.ABERTO


# ---------------------------------------------------------------------------
# Resolver — critérios da #28
# ---------------------------------------------------------------------------


def test_o_gestor_resolve_com_observacao(gestor, cenario, sessao, recarregar):
    id_alerta = cenario["alertas"][0]

    resposta = gestor.post(
        f"/alertas/{id_alerta}/resolver",
        data={"observacao": "Banco de capacitores religado"},
        follow_redirects=True,
    )

    assert resposta.status_code == 200
    recarregar()
    alerta = sessao.get(Alerta, id_alerta)
    assert alerta.status == StatusAlerta.RESOLVIDO
    assert alerta.observacao_resolucao == "Banco de capacitores religado"
    assert alerta.resolvido_em is not None
    assert alerta.id_usuario_resolucao is not None


def test_resolver_sem_observacao_nao_resolve(gestor, cenario, sessao, recarregar):
    """Critério da #28: observação obrigatória."""
    id_alerta = cenario["alertas"][0]

    resposta = gestor.post(
        f"/alertas/{id_alerta}/resolver", data={"observacao": "  "}, follow_redirects=True
    )

    assert "Escreva o que foi feito" in resposta.get_data(as_text=True)
    recarregar()
    assert sessao.get(Alerta, id_alerta).status == StatusAlerta.ABERTO


def test_o_resolvido_sai_da_lista_de_abertos(gestor, cenario, sessao, recarregar):
    """Critério da #28."""
    id_alerta = cenario["alertas"][0]
    gestor.post(f"/alertas/{id_alerta}/resolver",
                data={"observacao": "Capacitor religado"}, follow_redirects=True)
    recarregar()

    abertos = gestor.get("/alertas/?status=ABERTO").get_data(as_text=True)
    resolvidos = gestor.get("/alertas/?status=RESOLVIDO").get_data(as_text=True)

    assert "Capacitor religado" not in abertos
    assert "Capacitor religado" in resolvidos


def test_resolver_duas_vezes_nao_reescreve_quem_resolveu(gestor, cenario, sessao, recarregar):
    id_alerta = cenario["alertas"][0]
    gestor.post(f"/alertas/{id_alerta}/resolver",
                data={"observacao": "Primeira resolução"}, follow_redirects=True)

    resposta = gestor.post(f"/alertas/{id_alerta}/resolver",
                           data={"observacao": "Segunda resolução"}, follow_redirects=True)

    assert "já foi resolvido" in resposta.get_data(as_text=True)
    recarregar()
    assert sessao.get(Alerta, id_alerta).observacao_resolucao == "Primeira resolução"


def test_resolver_volta_para_os_mesmos_filtros(gestor, cenario):
    """Com 400 alertas por semana, cair na página 1 sem filtro a cada resolução
    tornaria a tela insuportável."""
    resposta = gestor.post(
        f"/alertas/{cenario['alertas'][0]}/resolver",
        data={"observacao": "Capacitor religado",
              "voltar_para": "/alertas/?status=ABERTO&tipo=FATOR_POTENCIA_BAIXO"},
    )

    assert resposta.status_code == 302
    assert "status=ABERTO" in resposta.headers["Location"]
    assert "tipo=FATOR_POTENCIA_BAIXO" in resposta.headers["Location"]


# ---------------------------------------------------------------------------
# Filtros e paginação — decisão de 10/10, obrigatórios
# ---------------------------------------------------------------------------


def test_filtra_por_tipo(gestor):
    corpo = gestor.get("/alertas/?tipo=CONSUMO_ACIMA_LIMITE").get_data(as_text=True)

    assert "MED-UTIL" in corpo
    assert "MED-PROD" not in corpo


def test_filtra_por_setor(gestor, cenario):
    corpo = gestor.get(f"/alertas/?setor={cenario['utilidades']}").get_data(as_text=True)

    assert "MED-UTIL" in corpo
    assert "MED-PROD" not in corpo


def test_filtro_invalido_na_url_nao_quebra_a_tela(gestor):
    """URL editada à mão vira 'sem filtro', não erro."""
    for consulta in ("?tipo=INVENTADO", "?status=XPTO", "?pagina=0", "?pagina=-5",
                     "?pagina=abc", "?setor=abc"):
        assert gestor.get(f"/alertas/{consulta}").status_code == 200


def test_pagina_mostra_o_total_e_a_posicao(gestor):
    corpo = gestor.get("/alertas/").get_data(as_text=True)

    assert "de 6 alertas" in corpo
    assert "página 1 de 1" in corpo


def test_os_totais_por_tipo_aparecem(gestor):
    corpo = gestor.get("/alertas/").get_data(as_text=True)

    assert "Fator de potência baixo" in corpo
    assert "Consumo acima do limite" in corpo


def test_o_painel_leva_para_a_tela_de_alertas(gestor):
    corpo = gestor.get("/painel").get_data(as_text=True)

    assert "/alertas/" in corpo
    assert "Ver todos e resolver" in corpo
