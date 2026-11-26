"""Testes do repositorio de usuarios contra o MySQL (issue #10).

Exige o banco de pe:  docker compose up -d db

O repositorio usa a sessao da requisicao (app/banco.sessao), entao estes testes
rodam dentro de um app_context.
"""

from werkzeug.security import check_password_hash

from app.models import PerfilUsuario
from app.repositories import usuario_repository


def test_encontra_o_usuario_pelo_email(app, usuarios):
    with app.app_context():
        encontrado = usuario_repository.buscar_por_email("gestor@gestenergia.local")

    assert encontrado is not None
    assert encontrado.perfil is PerfilUsuario.GESTOR
    assert encontrado.e_gestor is True


def test_email_com_maiusculas_tambem_encontra(app, usuarios):
    """A colacao do MySQL (utf8mb4_0900_ai_ci) ignora maiusculas."""
    with app.app_context():
        encontrado = usuario_repository.buscar_por_email("Gestor@GestEnergia.Local")

    assert encontrado is not None
    assert encontrado.email == "gestor@gestenergia.local"


def test_email_que_nao_existe_devolve_none(app, usuarios):
    with app.app_context():
        assert usuario_repository.buscar_por_email("ninguem@gestenergia.local") is None


def test_encontra_o_usuario_pelo_id(app, usuarios):
    id_do_operador = usuarios["operador"].id

    with app.app_context():
        encontrado = usuario_repository.buscar_por_id(id_do_operador)

    assert encontrado is not None
    assert encontrado.perfil is PerfilUsuario.OPERADOR
    assert encontrado.e_gestor is False


def test_id_que_nao_existe_devolve_none(app, usuarios):
    with app.app_context():
        assert usuario_repository.buscar_por_id(99999) is None


def test_o_hash_gravado_no_banco_nao_contem_a_senha(app, usuarios):
    """O que trafega e fica guardado e o hash, nunca a senha."""
    with app.app_context():
        encontrado = usuario_repository.buscar_por_email("operador@gestenergia.local")

    assert "operador123" not in encontrado.senha_hash
    assert check_password_hash(encontrado.senha_hash, "operador123")
