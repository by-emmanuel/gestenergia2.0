"""Regras de autenticacao e de acesso por perfil (issue #10).

Regra 7: OPERADOR registra e importa leituras; GESTOR faz tudo, inclusive
configurar limites e resolver alertas.

A senha e SEMPRE conferida por hash (werkzeug.security). Senha em texto nunca
entra no banco nem sai dele.
"""

from functools import wraps

from flask import abort, flash, redirect, url_for
from flask_login import current_user
from werkzeug.security import check_password_hash

from ..models import PerfilUsuario, Usuario
from ..repositories import usuario_repository

# Mensagem unica para email inexistente, senha errada e usuario inativo: dizer
# qual dos tres falhou entregaria a um atacante a informacao de quais emails
# existem no sistema.
ERRO_CREDENCIAL = "E-mail ou senha inválidos."


def autenticar(email: str, senha: str) -> tuple[Usuario | None, str | None]:
    """Confere as credenciais.

    Devolve (usuario, None) quando passa, ou (None, mensagem) quando falha.
    Nunca levanta excecao: quem chama transforma a mensagem em flash na tela.
    """
    email_limpo = (email or "").strip()
    if not email_limpo or not senha:
        return None, "Informe o e-mail e a senha."

    usuario = usuario_repository.buscar_por_email(email_limpo)
    if usuario is None:
        return None, ERRO_CREDENCIAL
    if not usuario.ativo:
        return None, ERRO_CREDENCIAL
    if not check_password_hash(usuario.senha_hash, senha):
        return None, ERRO_CREDENCIAL

    return usuario, None


def carregar_usuario(id_usuario: str) -> Usuario | None:
    """Recarrega o usuario da sessao a cada requisicao, para o Flask-Login.

    O id chega como texto no cookie. Id invalido devolve None, que o Flask-Login
    trata como visitante anonimo — nao como erro.
    """
    try:
        return usuario_repository.buscar_por_id(int(id_usuario))
    except (TypeError, ValueError):
        return None


def somente_gestor(rota):
    """Exige perfil GESTOR na rota, ja exigindo login antes.

    Operador autenticado recebe 403, nao um redirecionamento para o login: ele
    esta logado, o problema e o perfil. Visitante vai para a tela de login.
    """

    @wraps(rota)
    def envelope(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Faça login para continuar.", "erro")
            return redirect(url_for("auth.login"))
        if current_user.perfil is not PerfilUsuario.GESTOR:
            abort(403)
        return rota(*args, **kwargs)

    return envelope
