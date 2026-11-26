"""Fixtures compartilhadas pelos testes.

As de aplicacao (`app`, `cliente`) servem a todos, inclusive tests/unit, que nao
toca no banco.

As de banco (`motor`, `banco`, `sessao`, `usuarios`) exigem o MySQL de pe:

    docker compose up -d db

Ficam aqui, e nao em tests/integration/, porque tests/system tambem precisa
delas: o fluxo completo (login -> cadastro -> leituras -> alerta -> resolver)
roda contra banco de verdade. Fixture nao usada nao custa nada, entao definir
aqui nao atrasa os testes unitarios.

O schema do gestenergia_test e criado a partir de banco.Base.metadata, isto e,
dos proprios models. Se os models deixarem de espelhar o banco.sql, os testes
rodariam contra um schema diferente do real — e e exatamente isso que
tests/integration/test_models_no_mysql.py::test_models_espelham_o_banco_sql
detecta.
"""

import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash

from app import create_app
from app.banco import Base, fechar_sessao
from app.banco import motor as motor_da_aplicacao
from app.config import ConfigTeste
from app.models import PerfilUsuario, Usuario

# Senhas dos usuarios de teste. Iguais as de demonstracao do banco.sql, para o
# teste de sistema espelhar o que a pessoa digita na apresentacao.
SENHA_GESTOR = "gestor123"
SENHA_OPERADOR = "operador123"


@pytest.fixture
def app():
    """Aplicacao configurada para teste (usa o banco gestenergia_test).

    O motor e descartado no fim de CADA teste. Sem isso o pool de conexoes de
    cada aplicacao sobrevive ao teste que o criou, e uma conexao ociosa com
    transacao aberta segura o metadata lock da tabela: o drop_all do proximo
    teste fica preso em "Waiting for table metadata lock" e a suite trava.
    """
    aplicacao = create_app(ConfigTeste)
    yield aplicacao
    motor_da_aplicacao(aplicacao).dispose()


class ClienteDeTeste(FlaskClient):
    """Cliente que fecha a sessao do banco ao fim de cada requisicao.

    Em producao cada requisicao tem o seu contexto de aplicacao, entao a sessao
    nasce e morre com ela. No teste o pytest-flask mantem UM contexto para o
    teste inteiro, e requisicao dentro de contexto existente nao empilha outro:
    sem isto a mesma sessao atravessaria varias requisicoes, com o instantaneo
    de leitura congelado na primeira (o MySQL usa REPEATABLE READ) e sem ver o
    que o teste gravou depois. Fechar aqui faz o teste se comportar como a
    producao.
    """

    def open(self, *args, **kwargs):
        resposta = super().open(*args, **kwargs)
        fechar_sessao()
        return resposta


@pytest.fixture
def cliente(app):
    """Cliente de teste do Flask."""
    app.test_client_class = ClienteDeTeste
    return app.test_client()


def _esta_de_pe(motor: Engine) -> bool:
    """Diz se da para conectar, sem levantar excecao."""
    try:
        with motor.connect() as conexao:
            conexao.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture
def motor(app) -> Engine:
    """Motor da aplicacao de teste, apontando para o gestenergia_test."""
    motor_de_teste = motor_da_aplicacao(app)
    if not _esta_de_pe(motor_de_teste):
        pytest.skip("MySQL de teste indisponivel: rode 'docker compose up -d db'")
    return motor_de_teste


@pytest.fixture
def banco(motor: Engine) -> Engine:
    """Schema limpo no gestenergia_test, criado a partir dos models.

    Recriado a cada teste: sao 5 tabelas pequenas, sai barato, e cada teste
    comeca de um estado conhecido.
    """
    Base.metadata.drop_all(motor)
    Base.metadata.create_all(motor)
    yield motor
    # Antes do DROP, soltar tudo que possa segurar o metadata lock da tabela:
    # 1) a sessao que o pytest-flask deixa pendurada no contexto do teste;
    # 2) as conexoes ociosas do pool, que o dispose fecha.
    # Sem isso o drop_all fica preso em "Waiting for table metadata lock".
    fechar_sessao()
    motor.dispose()
    Base.metadata.drop_all(motor)


@pytest.fixture
def sessao(banco: Engine) -> Session:
    """Sessao aberta no banco de teste, fechada no fim."""
    with Session(banco, expire_on_commit=False) as sessao_aberta:
        yield sessao_aberta


@pytest.fixture
def usuarios(sessao: Session) -> dict[str, Usuario]:
    """Um GESTOR e um OPERADOR com hash de verdade, como no banco.sql."""
    gestor = Usuario(
        nome="Gestor de Energia",
        email="gestor@gestenergia.local",
        senha_hash=generate_password_hash(SENHA_GESTOR),
        perfil=PerfilUsuario.GESTOR,
    )
    operador = Usuario(
        nome="Operador de Planta",
        email="operador@gestenergia.local",
        senha_hash=generate_password_hash(SENHA_OPERADOR),
        perfil=PerfilUsuario.OPERADOR,
    )
    sessao.add_all([gestor, operador])
    sessao.commit()
    return {"gestor": gestor, "operador": operador}


@pytest.fixture
def recarregar(sessao: Session):
    """Faz a sessao do teste ver o que a aplicacao gravou depois.

    O MySQL usa REPEATABLE READ: uma vez iniciada, a transacao da sessao do
    teste mantem o mesmo instantaneo e nao enxerga commits de outra sessao.
    O commit encerra a transacao (a proxima leitura abre um instantaneo novo) e
    o expire_all descarta os objetos que ja estavam carregados.
    """

    def _recarregar() -> None:
        sessao.commit()
        sessao.expire_all()

    return _recarregar
