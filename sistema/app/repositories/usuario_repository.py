"""Acesso ao banco para usuarios (issue #10).

Unica camada que fala SQLAlchemy quando o assunto e usuario. As rotas nunca
chegam aqui direto: rota -> service -> repository.
"""

from sqlalchemy import select

from ..banco import sessao
from ..models import Usuario


def buscar_por_email(email: str) -> Usuario | None:
    """Devolve o usuario daquele email, ou None.

    O email e comparado como o MySQL compara: a colacao utf8mb4_0900_ai_ci
    ignora maiusculas, entao "Gestor@X" encontra "gestor@x".
    """
    return sessao().scalar(select(Usuario).where(Usuario.email == email))


def buscar_por_id(id_usuario: int) -> Usuario | None:
    """Devolve o usuario daquele id, ou None. Usado pelo Flask-Login."""
    return sessao().get(Usuario, id_usuario)


def salvar(usuario: Usuario) -> Usuario:
    """Grava o usuario (novo ou alterado) e devolve o mesmo objeto, ja com id."""
    sessao_atual = sessao()
    sessao_atual.add(usuario)
    sessao_atual.commit()
    return usuario


def desfazer() -> None:
    """Descarta a transacao pendente, depois de uma falha ao gravar."""
    sessao().rollback()
