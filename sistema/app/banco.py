"""Conexao com o MySQL e sessao do SQLAlchemy (issue #8).

A pilha e SQLAlchemy puro + PyMySQL, sem Flask-SQLAlchemy: o requirements.txt
nao traz essa dependencia e o CLAUDE.md fixa a stack.

O motor (engine) e criado UMA vez, quando a aplicacao sobe, e guardado em
app.extensions["banco"]. Criar motor por requisicao abriria um pool novo a cada
registro de leitura e comprometeria o limite de 500 ms da regra 8.

A sessao e por requisicao: fica em g e e fechada no fim do contexto. Quem usa a
sessao sao os repositorios (app/repositories/), nunca as rotas direto.
"""

from flask import Flask, current_app, g, has_app_context
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Base declarativa de todos os models (app/models.py)."""


def criar_motor(url_do_banco: str) -> Engine:
    """Cria o motor de conexao.

    pool_pre_ping testa a conexao antes de entregar, para o MySQL nao devolver
    conexao morta depois de ficar ocioso. connect_timeout curto para o /saude
    falhar rapido em vez de pendurar a tela.
    """
    return create_engine(
        url_do_banco,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3},
    )


def init_app(app: Flask) -> None:
    """Liga o SQLAlchemy a aplicacao. Chamado pelo create_app().

    Nao conecta no banco: o create_engine e preguicoso, a conexao so abre no
    primeiro uso. Assim a aplicacao sobe mesmo com o MySQL fora do ar, e quem
    diz o que esta errado e a rota /saude.
    """
    motor_da_app = criar_motor(app.config["SQLALCHEMY_DATABASE_URI"])

    app.extensions["banco"] = {
        "motor": motor_da_app,
        "fabrica_de_sessao": sessionmaker(bind=motor_da_app, expire_on_commit=False),
    }

    app.teardown_appcontext(_fechar_sessao)


def motor(app: Flask | None = None) -> Engine:
    """Motor da aplicacao. Sem argumento, usa a aplicacao do contexto atual."""
    alvo = app or current_app
    return alvo.extensions["banco"]["motor"]


def sessao() -> Session:
    """Sessao desta requisicao, criada na primeira chamada e reaproveitada."""
    if "sessao_do_banco" not in g:
        g.sessao_do_banco = current_app.extensions["banco"]["fabrica_de_sessao"]()
    return g.sessao_do_banco


def fechar_sessao() -> None:
    """Fecha a sessao do contexto atual, se houver uma aberta. Idempotente.

    Em producao quem chama e o teardown do contexto, no fim de cada requisicao.
    Nos testes ela e chamada a mao: o pytest-flask mantem um contexto de
    aplicacao pushado durante o teste inteiro, e requisicao dentro de contexto
    ja existente nao empilha outro — logo o teardown nao roda entre
    requisicoes, e a sessao ficaria aberta segurando o metadata lock da tabela.
    """
    if not has_app_context():
        return
    sessao_aberta = g.pop("sessao_do_banco", None)
    if sessao_aberta is not None:
        sessao_aberta.close()


def _fechar_sessao(_excecao: BaseException | None = None) -> None:
    """Assinatura que o teardown_appcontext do Flask espera."""
    fechar_sessao()
