"""Fluxo completo do CRUD de medidores pelas telas (issue #17).

Exige o banco de pé:  docker compose up -d db
"""

import pytest
from sqlalchemy import select

from app.models import Medidor, Setor
from tests.conftest import SENHA_GESTOR, SENHA_OPERADOR


def entrar(cliente, email, senha):
    return cliente.post("/login", data={"email": email, "senha": senha}, follow_redirects=True)


@pytest.fixture
def setores(sessao):
    """Dois setores ativos e um desativado, semeados pelo ORM."""
    producao = Setor(nome="Produção")
    utilidades = Setor(nome="Utilidades")
    antigo = Setor(nome="Antigo", ativo=False)
    sessao.add_all([producao, utilidades, antigo])
    sessao.commit()
    return {"producao": producao.id, "utilidades": utilidades.id, "antigo": antigo.id}


@pytest.fixture
def gestor(cliente, usuarios, setores):
    entrar(cliente, "gestor@gestenergia.local", SENHA_GESTOR)
    return cliente


@pytest.fixture
def operador(cliente, usuarios, setores):
    entrar(cliente, "operador@gestenergia.local", SENHA_OPERADOR)
    return cliente


def cadastrar(cliente, id_setor, codigo="MED-PROD", descricao=""):
    return cliente.post(
        "/medidores/novo",
        data={"codigo": codigo, "descricao": descricao, "id_setor": str(id_setor)},
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# Quem pode o quê (regra 7)
# ---------------------------------------------------------------------------


def test_visitante_e_mandado_para_o_login(cliente, usuarios):
    resposta = cliente.get("/medidores/")

    assert resposta.status_code == 302
    assert "/login" in resposta.headers["Location"]


def test_operador_ve_a_lista_mas_nao_o_botao(operador):
    resposta = operador.get("/medidores/")

    assert resposta.status_code == 200
    assert "Novo medidor" not in resposta.get_data(as_text=True)


@pytest.mark.parametrize("caminho", ["/medidores/novo", "/medidores/1/editar"])
def test_operador_recebe_403_nas_telas_de_edicao(operador, caminho):
    assert operador.get(caminho).status_code == 403


def test_operador_nao_cadastra_nem_pelo_post(operador, setores):
    resposta = operador.post(
        "/medidores/novo", data={"codigo": "MED-X", "id_setor": str(setores["producao"])}
    )

    assert resposta.status_code == 403


# ---------------------------------------------------------------------------
# Critério 1: código único
# ---------------------------------------------------------------------------


def test_gestor_cadastra_medidor(gestor, setores, sessao):
    resposta = cadastrar(gestor, setores["producao"], codigo="med-prod", descricao="Principal")

    assert resposta.status_code == 200
    assert "cadastrado" in resposta.get_data(as_text=True)
    medidor = sessao.scalar(select(Medidor).where(Medidor.codigo == "MED-PROD"))
    assert medidor is not None
    assert medidor.descricao == "Principal"


def test_codigo_repetido_nao_cadastra(gestor, setores):
    cadastrar(gestor, setores["producao"], codigo="MED-PROD")

    resposta = cadastrar(gestor, setores["utilidades"], codigo="MED-PROD")

    assert resposta.status_code == 400
    assert "Já existe um medidor" in resposta.get_data(as_text=True)


def test_codigo_repetido_ignorando_maiusculas(gestor, setores):
    cadastrar(gestor, setores["producao"], codigo="MED-PROD")

    resposta = cadastrar(gestor, setores["utilidades"], codigo="med-prod")

    assert resposta.status_code == 400
    assert "Já existe um medidor" in resposta.get_data(as_text=True)


def test_codigo_vazio_nao_cadastra(gestor, setores):
    resposta = cadastrar(gestor, setores["producao"], codigo="")

    assert resposta.status_code == 400
    assert "código do medidor é obrigatório" in resposta.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Critério 2: sempre ligado a um setor ativo
# ---------------------------------------------------------------------------


def test_o_formulario_nao_oferece_setor_desativado(gestor):
    corpo = gestor.get("/medidores/novo").get_data(as_text=True)

    assert "Produção" in corpo
    assert "Utilidades" in corpo
    assert "Antigo" not in corpo


def test_nao_cadastra_em_setor_desativado_nem_forcando_o_post(gestor, setores, sessao):
    """Esconder a opção não basta: a regra tem de valer no POST."""
    resposta = cadastrar(gestor, setores["antigo"], codigo="MED-X")

    assert resposta.status_code == 400
    assert "está desativado" in resposta.get_data(as_text=True)
    assert sessao.scalar(select(Medidor).where(Medidor.codigo == "MED-X")) is None


def test_setor_vazio_nao_cadastra(gestor):
    resposta = gestor.post(
        "/medidores/novo", data={"codigo": "MED-X", "id_setor": ""}, follow_redirects=True
    )

    assert resposta.status_code == 400
    assert "Escolha o setor do medidor." in resposta.get_data(as_text=True)


def test_a_lista_avisa_quando_o_setor_foi_desativado_depois(gestor, setores, sessao, recarregar):
    cadastrar(gestor, setores["producao"], codigo="MED-PROD")
    gestor.post(f"/setores/{setores['producao']}/alternar-ativo", follow_redirects=True)

    corpo = gestor.get("/medidores/").get_data(as_text=True)

    assert "setor desativado" in corpo
    # O medidor continua lá: desativar setor não apaga histórico.
    recarregar()
    assert sessao.scalar(select(Medidor).where(Medidor.codigo == "MED-PROD")) is not None


def test_a_edicao_ainda_oferece_o_setor_que_foi_desativado(gestor, setores, sessao):
    cadastrar(gestor, setores["producao"], codigo="MED-PROD")
    medidor = sessao.scalar(select(Medidor).where(Medidor.codigo == "MED-PROD"))
    gestor.post(f"/setores/{setores['producao']}/alternar-ativo", follow_redirects=True)

    corpo = gestor.get(f"/medidores/{medidor.id}/editar").get_data(as_text=True)

    assert "Produção (desativado)" in corpo


# ---------------------------------------------------------------------------
# Edição e desativação
# ---------------------------------------------------------------------------


def test_gestor_move_o_medidor_de_setor(gestor, setores, sessao, recarregar):
    cadastrar(gestor, setores["producao"], codigo="MED-X")
    medidor = sessao.scalar(select(Medidor).where(Medidor.codigo == "MED-X"))

    resposta = gestor.post(
        f"/medidores/{medidor.id}/editar",
        data={"codigo": "MED-X", "descricao": "", "id_setor": str(setores["utilidades"])},
        follow_redirects=True,
    )

    assert resposta.status_code == 200
    recarregar()
    assert sessao.scalar(select(Medidor).where(Medidor.id == medidor.id)).id_setor == setores[
        "utilidades"
    ]


def test_a_tela_de_edicao_vem_preenchida(gestor, setores, sessao):
    cadastrar(gestor, setores["producao"], codigo="MED-PROD", descricao="Principal")
    medidor = sessao.scalar(select(Medidor).where(Medidor.codigo == "MED-PROD"))

    corpo = gestor.get(f"/medidores/{medidor.id}/editar").get_data(as_text=True)

    assert 'value="MED-PROD"' in corpo
    assert 'value="Principal"' in corpo
    # O setor certo vem marcado, e os outros nao. O "selected" do Jinja cai em
    # outra linha, entao os espacos sao normalizados antes de comparar.
    compacto = " ".join(corpo.split())
    assert f'<option value="{setores["producao"]}" selected>' in compacto
    assert f'<option value="{setores["utilidades"]}" selected>' not in compacto


def test_editar_medidor_que_nao_existe_volta_para_a_lista(gestor):
    resposta = gestor.get("/medidores/9999/editar", follow_redirects=True)

    assert "Medidor não encontrado." in resposta.get_data(as_text=True)


def test_desativar_e_reativar_pela_tela(gestor, setores, sessao, recarregar):
    cadastrar(gestor, setores["producao"], codigo="MED-X")
    medidor = sessao.scalar(select(Medidor).where(Medidor.codigo == "MED-X"))

    resposta = gestor.post(f"/medidores/{medidor.id}/alternar-ativo", follow_redirects=True)
    assert "desativado" in resposta.get_data(as_text=True)
    recarregar()
    assert sessao.scalar(select(Medidor).where(Medidor.id == medidor.id)).ativo is False

    resposta = gestor.post(f"/medidores/{medidor.id}/alternar-ativo", follow_redirects=True)
    assert "reativado" in resposta.get_data(as_text=True)
    recarregar()
    assert sessao.scalar(select(Medidor).where(Medidor.id == medidor.id)).ativo is True


def test_a_lista_conta_as_leituras(gestor, setores):
    cadastrar(gestor, setores["producao"], codigo="MED-X")

    corpo = gestor.get("/medidores/").get_data(as_text=True)

    assert 'data-leituras="0"' in corpo


def test_sem_setor_ativo_o_formulario_explica_em_vez_de_quebrar(gestor, setores):
    for chave in ("producao", "utilidades"):
        gestor.post(f"/setores/{setores[chave]}/alternar-ativo", follow_redirects=True)

    corpo = gestor.get("/medidores/novo").get_data(as_text=True)

    assert "Não há setor ativo" in corpo


def test_o_menu_leva_aos_medidores(gestor):
    assert 'href="/medidores/"' in gestor.get("/").get_data(as_text=True)


def test_as_telas_de_medidor_nao_usam_cdn(gestor):
    for caminho in ["/medidores/", "/medidores/novo"]:
        assert "cdn" not in gestor.get(caminho).get_data(as_text=True).lower()
