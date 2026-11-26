"""Fluxo completo de login pelo cliente de teste do Flask (issue #10).

Exige o banco de pe:  docker compose up -d db

Estes testes passam pela tela, como a pessoa passa na apresentacao: enviam o
formulario, seguem o redirecionamento e leem o HTML que volta.
"""

import pytest

from app.services.auth_service import somente_gestor
from tests.conftest import SENHA_GESTOR, SENHA_OPERADOR


def entrar(cliente, email, senha, seguir=True):
    """Envia o formulario de login."""
    return cliente.post(
        "/login",
        data={"email": email, "senha": senha},
        follow_redirects=seguir,
    )


@pytest.fixture
def app_com_tela_de_gestor(app):
    """Registra uma rota protegida por perfil, para exercitar o decorador.

    As primeiras telas de GESTOR de verdade sao a #16 (configurar limites) e a
    #28 (resolver alertas). Enquanto elas nao existem, a rota abaixo vive so no
    teste — nao e tela de mentira no sistema.
    """

    @app.route("/area-do-gestor-para-teste")
    @somente_gestor
    def area_do_gestor_para_teste():
        return "Área exclusiva do gestor"

    return app


# ---------------------------------------------------------------------------
# Entrar e sair
# ---------------------------------------------------------------------------


def test_gestor_entra_e_a_tela_mostra_quem_esta_logado(cliente, usuarios):
    resposta = entrar(cliente, "gestor@gestenergia.local", SENHA_GESTOR)

    assert resposta.status_code == 200
    corpo = resposta.get_data(as_text=True)
    assert "Gestor de Energia" in corpo
    assert "GESTOR" in corpo
    assert "Sair" in corpo


def test_operador_entra(cliente, usuarios):
    resposta = entrar(cliente, "operador@gestenergia.local", SENHA_OPERADOR)

    assert resposta.status_code == 200
    corpo = resposta.get_data(as_text=True)
    assert "Operador de Planta" in corpo
    assert "OPERADOR" in corpo


def test_senha_errada_nao_entra_e_devolve_401(cliente, usuarios):
    resposta = entrar(cliente, "gestor@gestenergia.local", "senha-errada", seguir=False)

    assert resposta.status_code == 401
    corpo = resposta.get_data(as_text=True)
    assert "E-mail ou senha inválidos." in corpo
    assert "Sair" not in corpo


def test_email_que_nao_existe_nao_entra(cliente, usuarios):
    resposta = entrar(cliente, "ninguem@gestenergia.local", "qualquer", seguir=False)

    assert resposta.status_code == 401
    assert "E-mail ou senha inválidos." in resposta.get_data(as_text=True)


def test_a_senha_nunca_volta_no_html(cliente, usuarios):
    """O e-mail digitado volta preenchido; a senha, jamais."""
    resposta = entrar(cliente, "gestor@gestenergia.local", "senha-errada", seguir=False)

    corpo = resposta.get_data(as_text=True)
    assert "gestor@gestenergia.local" in corpo
    assert "senha-errada" not in corpo


def test_sair_encerra_a_sessao(cliente, usuarios):
    entrar(cliente, "gestor@gestenergia.local", SENHA_GESTOR)

    resposta = cliente.get("/logout", follow_redirects=True)

    assert resposta.status_code == 200
    corpo = resposta.get_data(as_text=True)
    assert "Sessão encerrada." in corpo
    assert "Entrar" in corpo
    # Depois de sair, a area protegida volta a exigir login.
    assert cliente.get("/conta").status_code == 302


def test_quem_ja_esta_logado_nao_ve_a_tela_de_login(cliente, usuarios):
    entrar(cliente, "gestor@gestenergia.local", SENHA_GESTOR)

    resposta = cliente.get("/login")

    assert resposta.status_code == 302
    assert resposta.headers["Location"] == "/"


# ---------------------------------------------------------------------------
# Rotas protegidas exigem login
# ---------------------------------------------------------------------------


def test_visitante_e_mandado_para_o_login(cliente, usuarios):
    resposta = cliente.get("/conta")

    assert resposta.status_code == 302
    assert "/login" in resposta.headers["Location"]


def test_visitante_ve_a_mensagem_de_que_precisa_entrar(cliente, usuarios):
    resposta = cliente.get("/conta", follow_redirects=True)

    assert "Faça login para continuar." in resposta.get_data(as_text=True)


def test_autenticado_acessa_a_conta(cliente, usuarios):
    entrar(cliente, "operador@gestenergia.local", SENHA_OPERADOR)

    resposta = cliente.get("/conta")

    assert resposta.status_code == 200
    assert "operador@gestenergia.local" in resposta.get_data(as_text=True)


def test_a_pagina_inicial_e_publica(cliente, usuarios):
    """A inicial e a porta de entrada: nao pode exigir login."""
    assert cliente.get("/").status_code == 200


def test_o_saude_continua_publico(cliente, usuarios):
    """O /saude e diagnostico de container, usado antes de existir sessao."""
    assert cliente.get("/saude").status_code == 200


def test_depois_de_entrar_volta_para_a_pagina_que_foi_pedida(cliente, usuarios):
    """O ?next= preserva o destino de quem bateu numa tela protegida."""
    resposta = cliente.post(
        "/login?next=/conta",
        data={"email": "gestor@gestenergia.local", "senha": SENHA_GESTOR},
        follow_redirects=False,
    )

    assert resposta.status_code == 302
    assert resposta.headers["Location"] == "/conta"


def test_next_para_fora_do_sistema_e_ignorado(cliente, usuarios):
    """Sem isto, um link malicioso usaria o nosso login para redirecionar fora."""
    resposta = cliente.post(
        "/login?next=https://site-falso.example",
        data={"email": "gestor@gestenergia.local", "senha": SENHA_GESTOR},
        follow_redirects=False,
    )

    assert resposta.headers["Location"] == "/"


# ---------------------------------------------------------------------------
# OPERADOR nao acessa telas do GESTOR (regra 7)
# ---------------------------------------------------------------------------


def test_gestor_acessa_a_area_do_gestor(app_com_tela_de_gestor, usuarios):
    cliente = app_com_tela_de_gestor.test_client()
    entrar(cliente, "gestor@gestenergia.local", SENHA_GESTOR)

    resposta = cliente.get("/area-do-gestor-para-teste")

    assert resposta.status_code == 200


def test_operador_recebe_403_na_area_do_gestor(app_com_tela_de_gestor, usuarios):
    """403, e nao redirecionamento: ele esta logado, o problema e o perfil."""
    cliente = app_com_tela_de_gestor.test_client()
    entrar(cliente, "operador@gestenergia.local", SENHA_OPERADOR)

    resposta = cliente.get("/area-do-gestor-para-teste")

    assert resposta.status_code == 403
    corpo = resposta.get_data(as_text=True)
    assert "Acesso negado" in corpo
    assert "GESTOR" in corpo


def test_visitante_na_area_do_gestor_vai_para_o_login(app_com_tela_de_gestor, usuarios):
    cliente = app_com_tela_de_gestor.test_client()

    resposta = cliente.get("/area-do-gestor-para-teste")

    assert resposta.status_code == 302
    assert "/login" in resposta.headers["Location"]
