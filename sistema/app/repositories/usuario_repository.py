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
