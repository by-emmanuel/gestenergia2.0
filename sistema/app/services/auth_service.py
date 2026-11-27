"""Regras de autenticacao e de acesso por perfil (issue #10).

Regra 7: OPERADOR registra e importa leituras; GESTOR faz tudo, inclusive
configurar limites e resolver alertas.

A senha e SEMPRE conferida por hash (werkzeug.security). Senha em texto nunca
entra no banco nem sai dele.
"""

from functools import wraps

from flask import abort, flash, redirect, url_for
from flask_login import current_user
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

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


# ---------------------------------------------------------------------------
# Cadastro publico
# ---------------------------------------------------------------------------

SENHA_MINIMA = 8
NOME_MAXIMO = 120   # tamanho da coluna usuarios_sistema.nome
EMAIL_MAXIMO = 180  # tamanho da coluna usuarios_sistema.email
ERRO_EMAIL_EM_USO = "Já existe uma conta com este e-mail."


def cadastrar(nome: str, email: str, senha: str, confirmacao: str) -> tuple[Usuario | None, str | None]:
    """Cria uma conta pelo formulario publico de cadastro.

    Toda conta criada aqui nasce OPERADOR (regra 7). O perfil NAO vem do
    formulario: se viesse, qualquer visitante poderia se cadastrar como GESTOR
    e passar a configurar limites e resolver alertas. Promover a gestor e uma
    decisao administrativa, feita fora da tela publica.

    Devolve (usuario, None) quando cria, ou (None, mensagem) quando recusa.
    """
    nome_limpo = " ".join((nome or "").split())
    email_limpo = (email or "").strip().lower()
    senha = senha or ""

    if not nome_limpo:
        return None, "Informe o seu nome."
    if len(nome_limpo) > NOME_MAXIMO:
        return None, f"O nome pode ter no máximo {NOME_MAXIMO} caracteres."
    if not _email_valido(email_limpo):
        return None, "Informe um e-mail válido."
    if len(email_limpo) > EMAIL_MAXIMO:
        return None, f"O e-mail pode ter no máximo {EMAIL_MAXIMO} caracteres."
    if len(senha) < SENHA_MINIMA:
        return None, f"A senha precisa ter pelo menos {SENHA_MINIMA} caracteres."
    if senha != (confirmacao or ""):
        return None, "A confirmação não confere com a senha."
    if usuario_repository.buscar_por_email(email_limpo) is not None:
        return None, ERRO_EMAIL_EM_USO

    usuario = Usuario(
        nome=nome_limpo,
        email=email_limpo,
        senha_hash=generate_password_hash(senha),
        perfil=PerfilUsuario.OPERADOR,
        ativo=True,
    )
    try:
        return usuario_repository.salvar(usuario), None
    except IntegrityError:
        # Dois cadastros simultaneos com o mesmo e-mail: a chave unica do banco
        # segura o segundo, que chegou depois da consulta acima.
        usuario_repository.desfazer()
        return None, ERRO_EMAIL_EM_USO


def _email_valido(email: str) -> bool:
    """Conferencia de formato simples: algo@dominio.tld, sem espacos."""
    if not email or " " in email or email.count("@") != 1:
        return False
    local, dominio = email.split("@")
    return bool(local) and "." in dominio.strip(".") and not dominio.startswith(".")
