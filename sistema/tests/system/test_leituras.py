"""Fluxo completo do registro de leituras pelas telas (issue #18).

Exige o banco de pé:  docker compose up -d db

Regra 7: registrar leitura é a atividade principal do OPERADOR, então as duas
telas valem para os dois perfis — não há restrição aqui.
"""

import pytest
from sqlalchemy import select

from app.models import Leitura, Medidor, Setor
from tests.conftest import SENHA_GESTOR, SENHA_OPERADOR


def entrar(cliente, email, senha):
    return cliente.post("/login", data={"email": email, "senha": senha}, follow_redirects=True)


@pytest.fixture
def medidor(sessao):
    """Um setor de Produção com um medidor ativo, semeados pelo ORM."""
    setor = Setor(nome="Produção", tem_fator_potencia=True)
    medidor = Medidor(setor=setor, codigo="MED-PROD")
    sessao.add(medidor)
    sessao.commit()
    return medidor.id


@pytest.fixture
def operador(cliente, usuarios, medidor):
    entrar(cliente, "operador@gestenergia.local", SENHA_OPERADOR)
    return cliente


@pytest.fixture
def gestor(cliente, usuarios, medidor):
    entrar(cliente, "gestor@gestenergia.local", SENHA_GESTOR)
    return cliente


def registrar(cliente, id_medidor, data_hora="2018-01-01T00:15", consumo="3,17", fator=""):
    return cliente.post(
        "/leituras/nova",
        data={
            "id_medidor": str(id_medidor),
            "data_hora": data_hora,
            "consumo_kwh": consumo,
            "fator_potencia": fator,
        },
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# Acesso
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("caminho", ["/leituras/", "/leituras/nova"])
def test_visitante_e_mandado_para_o_login(cliente, usuarios, caminho):
    resposta = cliente.get(caminho)

    assert resposta.status_code == 302
    assert "/login" in resposta.headers["Location"]


def test_o_operador_registra_leitura(operador, medidor, sessao, recarregar):
    """É a atividade principal do operador: não pode exigir GESTOR."""
    resposta = registrar(operador, medidor)

    assert resposta.status_code == 200
    assert "registrada" in resposta.get_data(as_text=True)
    recarregar()
    assert len(list(sessao.scalars(select(Leitura)))) == 1


def test_o_gestor_tambem_registra(gestor, medidor, sessao, recarregar):
    resposta = registrar(gestor, medidor, data_hora="2018-01-01T00:30")

    assert resposta.status_code == 200
    recarregar()
    assert len(list(sessao.scalars(select(Leitura)))) == 1


# ---------------------------------------------------------------------------
# Critério 1: duplicidade rejeitada com mensagem clara (regra 3)
# ---------------------------------------------------------------------------


def test_leitura_duplicada_e_rejeitada_com_mensagem_clara(operador, medidor, sessao, recarregar):
    registrar(operador, medidor, data_hora="2018-01-01T00:15")

    resposta = registrar(operador, medidor, data_hora="2018-01-01T00:15")

    assert resposta.status_code == 400
    corpo = resposta.get_data(as_text=True)
    assert "01/01/2018 às 00:15" in corpo
    assert "uma única leitura por data e hora" in corpo
    recarregar()
    assert len(list(sessao.scalars(select(Leitura)))) == 1


def test_o_formulario_devolve_o_que_foi_digitado_depois_da_duplicidade(operador, medidor):
    registrar(operador, medidor, consumo="3,17")

    resposta = registrar(operador, medidor, consumo="9,99")

    assert 'value="9,99"' in resposta.get_data(as_text=True)


def test_o_mesmo_medidor_em_outro_instante_e_aceito(operador, medidor, sessao, recarregar):
    registrar(operador, medidor, data_hora="2018-01-01T00:15")

    resposta = registrar(operador, medidor, data_hora="2018-01-01T00:30")

    assert resposta.status_code == 200
    recarregar()
    assert len(list(sessao.scalars(select(Leitura)))) == 2


def test_o_mesmo_instante_em_outro_medidor_e_aceito(operador, medidor, sessao, recarregar):
    """A chave única é (medidor, data_hora)."""
    outro = Medidor(id_setor=sessao.scalar(select(Setor)).id, codigo="MED-OUTRO")
    sessao.add(outro)
    sessao.commit()

    registrar(operador, medidor, data_hora="2018-01-01T00:15")
    resposta = registrar(operador, outro.id, data_hora="2018-01-01T00:15")

    assert resposta.status_code == 200
    recarregar()
    assert len(list(sessao.scalars(select(Leitura)))) == 2


# ---------------------------------------------------------------------------
# Critério 2: fator de potência aceito entre 0 e 1 (regra 6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fator", ["0", "0,91", "0,92", "0,93", "1"])
def test_fator_entre_0_e_1_e_aceito(operador, medidor, fator, sessao, recarregar):
    resposta = registrar(operador, medidor, fator=fator)

    assert resposta.status_code == 200
    recarregar()
    assert sessao.scalar(select(Leitura)).fator_potencia is not None


def test_fator_vazio_e_aceito_e_fica_nulo(operador, medidor, sessao, recarregar):
    """Regra 1: só a Produção tem o dado; sem ele não há alerta nem erro."""
    resposta = registrar(operador, medidor, fator="")

    assert resposta.status_code == 200
    recarregar()
    assert sessao.scalar(select(Leitura)).fator_potencia is None


def test_fator_em_percentual_e_recusado_com_a_conversao_sugerida(operador, medidor, sessao, recarregar):
    """Regra 6: a base vem em percentual; a tela aceita de 0 a 1."""
    resposta = registrar(operador, medidor, fator="73,21")

    assert resposta.status_code == 400
    corpo = resposta.get_data(as_text=True)
    assert "de 0 a 1" in corpo
    assert "0,7321" in corpo
    recarregar()
    assert list(sessao.scalars(select(Leitura))) == []


def test_fator_negativo_e_recusado(operador, medidor):
    resposta = registrar(operador, medidor, fator="-0,5")

    assert resposta.status_code == 400
    assert "não pode ser negativo" in resposta.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Outros campos
# ---------------------------------------------------------------------------


def test_consumo_vazio_nao_registra(operador, medidor):
    resposta = registrar(operador, medidor, consumo="")

    assert resposta.status_code == 400
    assert "Informe o consumo em kWh." in resposta.get_data(as_text=True)


def test_consumo_negativo_nao_registra(operador, medidor):
    resposta = registrar(operador, medidor, consumo="-1")

    assert resposta.status_code == 400
    assert "não pode ser negativo" in resposta.get_data(as_text=True)


def test_data_hora_vazia_nao_registra(operador, medidor):
    resposta = registrar(operador, medidor, data_hora="")

    assert resposta.status_code == 400
    assert "Informe a data e a hora da leitura." in resposta.get_data(as_text=True)


def test_medidor_desativado_nao_aparece_no_formulario(gestor, medidor):
    gestor.post(f"/medidores/{medidor}/alternar-ativo", follow_redirects=True)

    corpo = gestor.get("/leituras/nova").get_data(as_text=True)

    assert "Não há medidor ativo" in corpo


def test_medidor_desativado_nao_aceita_leitura_nem_forcando_o_post(gestor, medidor, sessao, recarregar):
    gestor.post(f"/medidores/{medidor}/alternar-ativo", follow_redirects=True)

    resposta = registrar(gestor, medidor)

    assert resposta.status_code == 400
    assert "está desativado" in resposta.get_data(as_text=True)
    recarregar()
    assert list(sessao.scalars(select(Leitura))) == []


# ---------------------------------------------------------------------------
# A lista
# ---------------------------------------------------------------------------


def test_a_lista_mostra_sem_previsao_ainda(operador, medidor):
    """Regra 4: com menos de 4 leituras anteriores, não há previsão — e isso não é erro."""
    registrar(operador, medidor)

    corpo = operador.get("/leituras/").get_data(as_text=True)

    assert "sem previsão ainda" in corpo


def test_a_lista_mostra_o_consumo_e_o_fator_com_virgula(operador, medidor):
    registrar(operador, medidor, consumo="3,17", fator="0,95")

    corpo = operador.get("/leituras/").get_data(as_text=True)

    assert "3,170" in corpo
    assert "0,950" in corpo


def test_a_lista_marca_o_fator_abaixo_do_minimo(operador, medidor):
    """0,91 fica abaixo de 0,92 e aparece destacado; o alerta em si é a #27."""
    registrar(operador, medidor, fator="0,91")

    corpo = operador.get("/leituras/").get_data(as_text=True)

    assert "fator-baixo" in corpo


def test_a_lista_nao_marca_o_fator_exatamente_no_minimo(operador, medidor):
    """Caso de borda do CLAUDE.md: exatamente 0,92 não é violação."""
    registrar(operador, medidor, fator="0,92")

    corpo = operador.get("/leituras/").get_data(as_text=True)

    assert "fator-baixo" not in corpo


def test_a_lista_mostra_tracinho_quando_nao_ha_fator(operador, medidor):
    registrar(operador, medidor, fator="")

    corpo = operador.get("/leituras/").get_data(as_text=True)

    assert "Este setor não mede fator de potência" in corpo


def test_as_recentes_vem_primeiro(operador, medidor):
    registrar(operador, medidor, data_hora="2018-01-01T00:15", consumo="10")
    registrar(operador, medidor, data_hora="2018-01-01T00:30", consumo="20")

    corpo = operador.get("/leituras/").get_data(as_text=True)

    assert corpo.index("01/01/2018 00:30") < corpo.index("01/01/2018 00:15")


def test_a_lista_vazia_explica_de_onde_vem_leitura(operador):
    corpo = operador.get("/leituras/").get_data(as_text=True)

    assert "Nenhuma leitura registrada." in corpo


def test_depois_de_registrar_o_medidor_fica_mantido(operador, medidor):
    """Quem registra leitura normalmente registra várias do mesmo medidor."""
    resposta = operador.post(
        "/leituras/nova",
        data={
            "id_medidor": str(medidor),
            "data_hora": "2018-01-01T00:15",
            "consumo_kwh": "3,17",
            "fator_potencia": "",
        },
        follow_redirects=False,
    )

    assert resposta.status_code == 302
    assert f"id_medidor={medidor}" in resposta.headers["Location"]


def test_o_menu_leva_as_leituras(operador):
    assert 'href="/leituras/"' in operador.get("/").get_data(as_text=True)


def test_as_telas_de_leitura_nao_usam_cdn(operador):
    for caminho in ["/leituras/", "/leituras/nova"]:
        assert "cdn" not in operador.get(caminho).get_data(as_text=True).lower()
