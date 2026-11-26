"""Fluxo completo do CRUD de setores pelas telas (issue #16).

Exige o banco de pé:  docker compose up -d db

Regra 7: o OPERADOR vê a lista, porque precisa saber em que setor está
registrando leitura, mas só o GESTOR cadastra, edita e desativa.
"""

from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Leitura, Medidor, Setor
from tests.conftest import SENHA_GESTOR, SENHA_OPERADOR


def entrar(cliente, email, senha):
    return cliente.post("/login", data={"email": email, "senha": senha}, follow_redirects=True)


@pytest.fixture
def gestor(cliente, usuarios):
    entrar(cliente, "gestor@gestenergia.local", SENHA_GESTOR)
    return cliente


@pytest.fixture
def operador(cliente, usuarios):
    entrar(cliente, "operador@gestenergia.local", SENHA_OPERADOR)
    return cliente


def cadastrar(cliente, **campos):
    dados = {"nome": "Produção", "descricao": "", "limite_consumo_kwh": "", "arquivo_modelo": ""}
    dados.update(campos)
    return cliente.post("/setores/novo", data=dados, follow_redirects=True)


# ---------------------------------------------------------------------------
# Quem pode o quê (regra 7)
# ---------------------------------------------------------------------------


def test_visitante_e_mandado_para_o_login(cliente, usuarios):
    resposta = cliente.get("/setores/")

    assert resposta.status_code == 302
    assert "/login" in resposta.headers["Location"]


def test_operador_ve_a_lista(operador):
    resposta = operador.get("/setores/")

    assert resposta.status_code == 200
    assert "Setores" in resposta.get_data(as_text=True)


def test_operador_nao_ve_o_botao_de_novo_setor(operador):
    corpo = operador.get("/setores/").get_data(as_text=True)

    assert "Novo setor" not in corpo
    assert "ação do perfil GESTOR" in corpo


@pytest.mark.parametrize("caminho", ["/setores/novo", "/setores/1/editar"])
def test_operador_recebe_403_nas_telas_de_edicao(operador, caminho):
    resposta = operador.get(caminho)

    assert resposta.status_code == 403
    assert "Acesso negado" in resposta.get_data(as_text=True)


def test_operador_nao_consegue_cadastrar_nem_pelo_post(operador):
    """O 403 tem de valer no POST também, não só na tela."""
    resposta = operador.post("/setores/novo", data={"nome": "Setor do operador"})

    assert resposta.status_code == 403


def test_operador_nao_consegue_desativar(operador, setor_existente):
    resposta = operador.post(f"/setores/{setor_existente}/alternar-ativo")

    assert resposta.status_code == 403


@pytest.fixture
def setor_existente(sessao):
    """Um setor já no banco, semeado pelo ORM.

    Semeado direto, e não pelas telas do gestor, para não disputar a sessão de
    login com o operador no mesmo cliente de teste.
    """
    setor = Setor(nome="Produção", limite_consumo_kwh=Decimal("122.71"))
    sessao.add(setor)
    sessao.commit()
    return setor.id


# ---------------------------------------------------------------------------
# O gestor cadastra, edita e desativa
# ---------------------------------------------------------------------------


def test_gestor_cadastra_setor(gestor, sessao):
    resposta = cadastrar(
        gestor,
        nome="Produção",
        descricao="Linha de produção",
        limite_consumo_kwh="122,71",
        arquivo_modelo="modelo_consumo_producao.pkl",
        tem_fator_potencia="on",
    )

    assert resposta.status_code == 200
    assert "cadastrado" in resposta.get_data(as_text=True)
    setor = sessao.scalar(select(Setor).where(Setor.nome == "Produção"))
    assert setor.limite_consumo_kwh == Decimal("122.710")
    assert setor.tem_fator_potencia is True


def test_a_lista_mostra_o_limite_com_virgula(gestor):
    cadastrar(gestor, nome="Produção", limite_consumo_kwh="122,71")

    corpo = gestor.get("/setores/").get_data(as_text=True)

    assert "122,710" in corpo


def test_setor_sem_limite_aparece_como_sem_limite(gestor):
    """Regra 10: sem limite, o setor não gera alerta de consumo."""
    cadastrar(gestor, nome="Administrativo")

    corpo = gestor.get("/setores/").get_data(as_text=True)

    assert "sem limite" in corpo
    assert "sem modelo" in corpo


def test_nome_vazio_nao_cadastra_e_devolve_400(gestor):
    resposta = cadastrar(gestor, nome="")

    assert resposta.status_code == 400
    assert "nome do setor é obrigatório" in resposta.get_data(as_text=True)


def test_limite_zero_nao_cadastra(gestor, sessao):
    resposta = cadastrar(gestor, nome="Setor zerado", limite_consumo_kwh="0")

    assert resposta.status_code == 400
    assert "maior que zero" in resposta.get_data(as_text=True)
    assert sessao.scalar(select(Setor).where(Setor.nome == "Setor zerado")) is None


def test_o_formulario_devolve_o_que_foi_digitado_depois_do_erro(gestor):
    """Quem errou um campo não deve perder os outros."""
    resposta = cadastrar(gestor, nome="", descricao="Linha de produção")

    assert "Linha de produção" in resposta.get_data(as_text=True)


def test_nome_repetido_nao_cadastra(gestor):
    cadastrar(gestor, nome="Utilidades")

    resposta = cadastrar(gestor, nome="Utilidades")

    assert resposta.status_code == 400
    assert "Já existe um setor" in resposta.get_data(as_text=True)


def test_gestor_edita_o_limite(gestor, sessao, recarregar):
    cadastrar(gestor, nome="Produção")
    setor = sessao.scalar(select(Setor).where(Setor.nome == "Produção"))

    resposta = gestor.post(
        f"/setores/{setor.id}/editar",
        data={"nome": "Produção", "descricao": "", "limite_consumo_kwh": "99,5", "arquivo_modelo": ""},
        follow_redirects=True,
    )

    assert resposta.status_code == 200
    recarregar()
    assert sessao.scalar(select(Setor).where(Setor.id == setor.id)).limite_consumo_kwh == Decimal(
        "99.500"
    )


def test_a_tela_de_edicao_vem_preenchida(gestor, sessao):
    cadastrar(gestor, nome="Produção", limite_consumo_kwh="122,71")
    setor = sessao.scalar(select(Setor).where(Setor.nome == "Produção"))

    corpo = gestor.get(f"/setores/{setor.id}/editar").get_data(as_text=True)

    assert 'value="Produção"' in corpo
    assert 'value="122,710"' in corpo


def test_editar_setor_que_nao_existe_volta_para_a_lista(gestor):
    resposta = gestor.get("/setores/9999/editar", follow_redirects=True)

    assert "Setor não encontrado." in resposta.get_data(as_text=True)


def test_desativar_e_reativar_pela_tela(gestor, sessao, recarregar):
    cadastrar(gestor, nome="Produção")
    setor = sessao.scalar(select(Setor).where(Setor.nome == "Produção"))

    resposta = gestor.post(f"/setores/{setor.id}/alternar-ativo", follow_redirects=True)
    assert "desativado" in resposta.get_data(as_text=True)
    recarregar()
    assert sessao.scalar(select(Setor).where(Setor.id == setor.id)).ativo is False

    resposta = gestor.post(f"/setores/{setor.id}/alternar-ativo", follow_redirects=True)
    assert "reativado" in resposta.get_data(as_text=True)
    recarregar()
    assert sessao.scalar(select(Setor).where(Setor.id == setor.id)).ativo is True


def test_desativar_pela_tela_nao_apaga_historico(gestor, sessao):
    """O critério da issue: desativar não apaga nada."""
    cadastrar(gestor, nome="Produção")
    setor = sessao.scalar(select(Setor).where(Setor.nome == "Produção"))
    medidor = Medidor(id_setor=setor.id, codigo="MED-PROD")
    sessao.add(
        Leitura(medidor=medidor, data_hora=datetime(2018, 1, 1, 0, 15), consumo_kwh=Decimal("10"))
    )
    sessao.commit()

    gestor.post(f"/setores/{setor.id}/alternar-ativo", follow_redirects=True)

    assert sessao.scalar(select(Medidor).where(Medidor.codigo == "MED-PROD")) is not None
    assert len(list(sessao.scalars(select(Leitura)))) == 1


def test_a_lista_mostra_quantos_medidores_o_setor_tem(gestor, sessao):
    cadastrar(gestor, nome="Produção")
    setor = sessao.scalar(select(Setor).where(Setor.nome == "Produção"))
    sessao.add_all(
        [Medidor(id_setor=setor.id, codigo="MED-1"), Medidor(id_setor=setor.id, codigo="MED-2")]
    )
    sessao.commit()

    corpo = gestor.get("/setores/").get_data(as_text=True)

    assert "Produção" in corpo
    assert 'data-medidores="2"' in corpo


def test_o_menu_leva_aos_setores_depois_de_entrar(gestor):
    corpo = gestor.get("/").get_data(as_text=True)

    assert 'href="/setores/"' in corpo


def test_as_telas_de_setor_nao_usam_cdn(gestor):
    """CLAUDE.md: nada de CDN nas telas finais."""
    for caminho in ["/setores/", "/setores/novo"]:
        assert "cdn" not in gestor.get(caminho).get_data(as_text=True).lower()
