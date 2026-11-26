"""Testes das regras de autenticacao sem banco (issue #10).

O repositorio e trocado por um dublê, entao estes testes conferem a REGRA:
quem entra, quem nao entra e, principalmente, que a mensagem de erro e a mesma
nos tres casos de falha.
"""

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

from app.models import PerfilUsuario, Usuario
from app.services import auth_service


def _usuario(senha="senha-correta", perfil=PerfilUsuario.OPERADOR, ativo=True):
    return Usuario(
        id=1,
        nome="Operador de Planta",
        email="operador@gestenergia.local",
        senha_hash=generate_password_hash(senha),
        perfil=perfil,
        ativo=ativo,
    )


@pytest.fixture
def repositorio_com(monkeypatch):
    """Faz o auth_service encontrar (ou nao) o usuario que o teste quiser."""

    def configurar(usuario):
        monkeypatch.setattr(
            auth_service.usuario_repository, "buscar_por_email", lambda email: usuario
        )

    return configurar


def test_autentica_com_a_senha_certa(repositorio_com):
    repositorio_com(_usuario())

    usuario, erro = auth_service.autenticar("operador@gestenergia.local", "senha-correta")

    assert erro is None
    assert usuario.email == "operador@gestenergia.local"


def test_recusa_a_senha_errada(repositorio_com):
    repositorio_com(_usuario())

    usuario, erro = auth_service.autenticar("operador@gestenergia.local", "senha-errada")

    assert usuario is None
    assert erro == auth_service.ERRO_CREDENCIAL


def test_recusa_email_que_nao_existe(repositorio_com):
    repositorio_com(None)

    usuario, erro = auth_service.autenticar("ninguem@gestenergia.local", "qualquer")

    assert usuario is None
    assert erro == auth_service.ERRO_CREDENCIAL


def test_recusa_usuario_desativado_mesmo_com_a_senha_certa(repositorio_com):
    repositorio_com(_usuario(ativo=False))

    usuario, erro = auth_service.autenticar("operador@gestenergia.local", "senha-correta")

    assert usuario is None
    assert erro == auth_service.ERRO_CREDENCIAL


def test_a_mensagem_de_erro_nao_revela_se_o_email_existe(repositorio_com):
    """Mensagens diferentes entregariam quais e-mails estao cadastrados."""
    repositorio_com(None)
    _, erro_email_inexistente = auth_service.autenticar("ninguem@x.local", "qualquer")

    repositorio_com(_usuario())
    _, erro_senha_errada = auth_service.autenticar("operador@gestenergia.local", "errada")

    repositorio_com(_usuario(ativo=False))
    _, erro_desativado = auth_service.autenticar("operador@gestenergia.local", "senha-correta")

    assert erro_email_inexistente == erro_senha_errada == erro_desativado


@pytest.mark.parametrize(
    "email, senha",
    [("", "senha"), ("operador@gestenergia.local", ""), ("   ", "senha"), ("", "")],
)
def test_campo_vazio_pede_os_dois_campos(repositorio_com, email, senha):
    repositorio_com(_usuario())

    usuario, erro = auth_service.autenticar(email, senha)

    assert usuario is None
    assert erro == "Informe o e-mail e a senha."


def test_espaco_em_volta_do_email_e_ignorado(repositorio_com):
    repositorio_com(_usuario())

    usuario, erro = auth_service.autenticar("  operador@gestenergia.local  ", "senha-correta")

    assert erro is None
    assert usuario is not None


def test_senha_nunca_e_guardada_em_texto():
    """A senha nao pode aparecer dentro do hash, e o hash tem de ser verificavel.

    O algoritmo nao e fixado de proposito: o Werkzeug 3.1.3 gera scrypt por
    padrao, enquanto os usuarios de demonstracao do banco.sql tem pbkdf2. O
    check_password_hash verifica os dois, entao o que importa e a propriedade,
    nao o nome do algoritmo.
    """
    usuario = _usuario(senha="operador123")

    assert "operador123" not in usuario.senha_hash
    assert check_password_hash(usuario.senha_hash, "operador123")
    assert not check_password_hash(usuario.senha_hash, "operador124")


def test_carregar_usuario_com_id_invalido_devolve_none(monkeypatch):
    """Cookie adulterado nao pode virar erro 500."""
    monkeypatch.setattr(
        auth_service.usuario_repository, "buscar_por_id", lambda id_usuario: _usuario()
    )

    assert auth_service.carregar_usuario("nao-e-numero") is None
    assert auth_service.carregar_usuario(None) is None
    assert auth_service.carregar_usuario("1") is not None


def test_usuario_desativado_nao_abre_sessao_no_flask_login():
    """O is_active do model manda, nao o padrao do UserMixin (que e sempre True)."""
    assert _usuario(ativo=True).is_active is True
    assert _usuario(ativo=False).is_active is False


def test_get_id_devolve_texto_para_o_cookie():
    assert _usuario().get_id() == "1"
