"""Cadastro publico de conta, pela tela (como a pessoa usa).

Exige o banco de pe:  docker compose up -d db

A regra central: toda conta criada pelo cadastro publico e OPERADOR. O perfil
nunca vem do formulario, nem se alguem o enviar a mao.
"""

import pytest
from sqlalchemy import func, select
from werkzeug.security import check_password_hash

from app.models import PerfilUsuario, Usuario

SENHA = "senha-forte-123"


def cadastrar(cliente, seguir=True, **campos):
    """Envia o formulario de cadastro; campos nao informados vem validos."""
    dados = {
        "nome": "Maria Operadora",
        "email": "maria@gestenergia.local",
        "senha": SENHA,
        "confirmacao": SENHA,
    }
    dados.update(campos)
    return cliente.post("/cadastro", data=dados, follow_redirects=seguir)


def buscar(sessao, recarregar, email):
    recarregar()
    return sessao.scalar(select(Usuario).where(Usuario.email == email))


def contar(sessao, recarregar):
    recarregar()
    return sessao.scalar(select(func.count()).select_from(Usuario))


# ---------------------------------------------------------------------------
# Tela
# ---------------------------------------------------------------------------


def test_tela_de_cadastro_abre(cliente, banco):
    resposta = cliente.get("/cadastro")

    assert resposta.status_code == 200
    corpo = resposta.get_data(as_text=True)
    assert "Criar conta" in corpo
    assert 'name="confirmacao"' in corpo
    # Nao ha como escolher perfil na tela publica.
    assert 'name="perfil"' not in corpo


def test_login_e_cadastro_apontam_um_para_o_outro(cliente, banco):
    assert "/cadastro" in cliente.get("/login").get_data(as_text=True)
    assert "/login" in cliente.get("/cadastro").get_data(as_text=True)


def test_quem_ja_esta_logado_nao_ve_o_cadastro(cliente, usuarios):
    cliente.post("/login", data={"email": "gestor@gestenergia.local", "senha": "gestor123"})

    resposta = cliente.get("/cadastro")

    assert resposta.status_code == 302
    assert resposta.headers["Location"] == "/"


# ---------------------------------------------------------------------------
# Cadastro que da certo
# ---------------------------------------------------------------------------


def test_cadastro_cria_operador_e_ja_entra(cliente, sessao, recarregar, banco):
    resposta = cadastrar(cliente)

    assert resposta.status_code == 200
    assert "Conta criada. Bem-vindo, Maria Operadora." in resposta.get_data(as_text=True)

    usuario = buscar(sessao, recarregar, "maria@gestenergia.local")
    assert usuario is not None
    assert usuario.perfil is PerfilUsuario.OPERADOR
    assert usuario.ativo is True
    # A sessao ja esta aberta: a area protegida responde.
    assert cliente.get("/conta").status_code == 200


def test_senha_vai_em_hash_e_nunca_em_texto(cliente, sessao, recarregar, banco):
    cadastrar(cliente)

    usuario = buscar(sessao, recarregar, "maria@gestenergia.local")
    assert usuario.senha_hash != SENHA
    assert SENHA not in usuario.senha_hash
    assert check_password_hash(usuario.senha_hash, SENHA)


def test_conta_criada_entra_pelo_login_depois(cliente, banco):
    cadastrar(cliente)
    cliente.get("/logout")

    resposta = cliente.post(
        "/login", data={"email": "maria@gestenergia.local", "senha": SENHA}, follow_redirects=True
    )

    assert "Bem-vindo, Maria Operadora." in resposta.get_data(as_text=True)


def test_perfil_enviado_a_mao_e_ignorado(cliente, sessao, recarregar, banco):
    """Quem forja o POST com perfil=GESTOR continua OPERADOR."""
    cadastrar(cliente, perfil="GESTOR")

    usuario = buscar(sessao, recarregar, "maria@gestenergia.local")
    assert usuario.perfil is PerfilUsuario.OPERADOR


def test_email_e_nome_sao_normalizados(cliente, sessao, recarregar, banco):
    cadastrar(cliente, nome="  Maria   Operadora ", email="  Maria@GestEnergia.LOCAL ")

    usuario = buscar(sessao, recarregar, "maria@gestenergia.local")
    assert usuario.email == "maria@gestenergia.local"
    assert usuario.nome == "Maria Operadora"


# ---------------------------------------------------------------------------
# Cadastro recusado
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("campos", "mensagem"),
    [
        ({"nome": "   "}, "Informe o seu nome."),
        ({"nome": "x" * 121}, "O nome pode ter no máximo 120 caracteres."),
        ({"email": "sem-arroba"}, "Informe um e-mail válido."),
        ({"email": "maria@semponto"}, "Informe um e-mail válido."),
        ({"email": "ma ria@gestenergia.local"}, "Informe um e-mail válido."),
        ({"senha": "curta12", "confirmacao": "curta12"}, "A senha precisa ter pelo menos 8 caracteres."),
        ({"confirmacao": "outra-senha-123"}, "A confirmação não confere com a senha."),
    ],
)
def test_dados_invalidos_sao_recusados(cliente, sessao, recarregar, banco, campos, mensagem):
    resposta = cadastrar(cliente, **campos)

    assert resposta.status_code == 400
    assert mensagem in resposta.get_data(as_text=True)
    assert contar(sessao, recarregar) == 0


def test_email_repetido_e_recusado_sem_diferenciar_maiusculas(cliente, sessao, recarregar, usuarios):
    resposta = cadastrar(cliente, email="Gestor@GestEnergia.Local")

    assert resposta.status_code == 400
    assert "Já existe uma conta com este e-mail." in resposta.get_data(as_text=True)
    assert contar(sessao, recarregar) == 2  # so os dois da fixture


def test_erro_devolve_nome_e_email_mas_nunca_a_senha(cliente, banco):
    resposta = cadastrar(cliente, confirmacao="outra-senha-123")

    corpo = resposta.get_data(as_text=True)
    assert 'value="Maria Operadora"' in corpo
    assert 'value="maria@gestenergia.local"' in corpo
    assert SENHA not in corpo
    assert "outra-senha-123" not in corpo


def test_recusa_nao_abre_sessao(cliente, banco):
    cadastrar(cliente, confirmacao="outra-senha-123")

    assert cliente.get("/conta").status_code == 302
