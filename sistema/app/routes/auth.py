"""Blueprint de autenticacao (issue #10).

A rota so valida o formulario, chama o service e devolve o template. Quem
confere a senha e o auth_service; quem fala com o banco e o repository.
"""

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..services.auth_service import autenticar, cadastrar

bp = Blueprint("auth", __name__)

# Marca, na sessao, que a proxima pagina deve animar a chegada dos itens do
# menu que so existem para quem entrou. Lida e apagada uma unica vez pelo
# context processor em app/__init__.py.
CHAVE_REVELAR_MENU = "revelar_menu"


@bp.route("/login", methods=["GET", "POST"])
def login():
    """Tela de login. Quem ja esta autenticado vai direto para a inicial."""
    if current_user.is_authenticated:
        return redirect(url_for("painel.inicio"))

    if request.method == "POST":
        usuario, erro = autenticar(request.form.get("email", ""), request.form.get("senha", ""))
        if erro:
            flash(erro, "erro")
            # Devolve 401, e nao 200, para o erro aparecer tambem em teste e log.
            return render_template("login.html", email=request.form.get("email", "")), 401

        login_user(usuario)
        session[CHAVE_REVELAR_MENU] = True
        flash(f"Bem-vindo, {usuario.nome}.", "sucesso")
        return redirect(_destino_seguro() or url_for("painel.inicio"))

    return render_template("login.html", email="")


@bp.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    """Cadastro publico. A conta criada e sempre OPERADOR (ver auth_service).

    Deu certo: a pessoa ja entra logada. Deu errado: a tela volta com nome e
    e-mail preenchidos, mas nunca com a senha.
    """
    if current_user.is_authenticated:
        return redirect(url_for("painel.inicio"))

    if request.method == "POST":
        usuario, erro = cadastrar(
            request.form.get("nome", ""),
            request.form.get("email", ""),
            request.form.get("senha", ""),
            request.form.get("confirmacao", ""),
        )
        if erro:
            flash(erro, "erro")
            return render_template(
                "cadastro.html",
                nome=request.form.get("nome", ""),
                email=request.form.get("email", ""),
            ), 400

        login_user(usuario)
        session[CHAVE_REVELAR_MENU] = True
        flash(f"Conta criada. Bem-vindo, {usuario.nome}.", "sucesso")
        return redirect(url_for("painel.inicio"))

    return render_template("cadastro.html", nome="", email="")


@bp.route("/logout")
@login_required
def logout():
    """Encerra a sessao."""
    logout_user()
    flash("Sessão encerrada.", "sucesso")
    return redirect(url_for("auth.login"))


def _destino_seguro() -> str | None:
    """Le o ?next= do formulario, aceitando so caminho interno.

    Sem isso, um link com ?next=https://site-falso deixaria o nosso login
    redirecionar para fora depois de autenticar (open redirect).
    """
    destino = request.args.get("next") or request.form.get("next") or ""
    if destino.startswith("/") and not destino.startswith("//"):
        return destino
    return None
