"""Verificacao de saude da aplicacao (issue #9).

Desde a issue #8 usa o motor da propria aplicacao, criado uma unica vez no
create_app(), em vez de abrir um motor proprio a cada chamada. Assim o /saude
testa a MESMA conexao que o sistema usa — um /saude verde com o pool da
aplicacao quebrado seria um diagnostico inutil.
"""

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError


def verificar_banco(motor: Engine) -> tuple[bool, str]:
    """Tenta um SELECT 1 no banco, usando o motor da aplicacao.

    Devolve (True, versao_do_mysql) quando conecta, ou (False, motivo) quando falha.
    Nunca levanta excecao: quem chama quer o diagnostico, nao o erro.
    """
    try:
        with motor.connect() as conexao:
            conexao.execute(text("SELECT 1"))
            versao = conexao.execute(text("SELECT VERSION()")).scalar_one()
        return True, str(versao)
    except SQLAlchemyError as erro:
        return False, type(erro).__name__
    except Exception as erro:  # driver ausente, DNS, etc.
        return False, type(erro).__name__
