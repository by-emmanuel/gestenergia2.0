"""Fabrica da aplicacao Flask (issue #9).

Sobe a aplicacao, liga o SQLAlchemy (issue #8) e o Flask-Login (issue #10),
carrega os modelos de ml/ (issue #26) e serve a pagina inicial e a rota /saude.

    flask --app app run --debug
"""

from flask import Flask
from flask_login import LoginManager

from . import banco
from .config import Config

gerenciador_de_login = LoginManager()


def create_app(config=Config) -> Flask:
    """Cria e configura a aplicacao."""
    app = Flask(__name__)
    app.config.from_object(config)

    banco.init_app(app)
    # Importar os models registra as 5 tabelas em banco.Base.metadata. Sem isto
    # o metadata fica vazio e o create_all dos testes nao criaria nada.
    from . import models  # noqa: F401

    _carregar_modelos(app)
    _configurar_login(app)
    _registrar_blueprints(app)
    _registrar_tratadores_de_erro(app)
    _registrar_comandos(app)

    return app


def _registrar_comandos(app: Flask) -> None:
    """Comandos de linha de comando (issue #49)."""
    from .cli import carregar_demonstracao

    app.cli.add_command(carregar_demonstracao)


def _carregar_modelos(app: Flask) -> None:
    """Regra 9: os 4 modelos sobem UMA VEZ, aqui, e nao a cada leitura.

    Carregar o .pkl por leitura estouraria os 500 ms da regra 8 — ler o arquivo
    custa mais que a previsao inteira. Pasta ausente ou modelo que nao carrega
    nao impedem a aplicacao de subir: o setor correspondente passa a devolver
    None e a tela mostra "sem previsao ainda".
    """
    from .services import previsao_service

    app.extensions["modelos"] = previsao_service.carregar_modelos(app.config["CAMINHO_MODELO"])


def _registrar_tratadores_de_erro(app: Flask) -> None:
    """Telas de erro em portugues, no mesmo layout do resto do sistema."""
    from flask import render_template

    @app.errorhandler(403)
    def acesso_negado(_erro):
        """Perfil sem permissao (regra 7): o usuario esta logado, falta perfil."""
        return render_template("403.html"), 403


def _configurar_login(app: Flask) -> None:
    """Liga o Flask-Login: para onde mandar quem nao esta autenticado."""
    from .services.auth_service import carregar_usuario

    gerenciador_de_login.init_app(app)
    gerenciador_de_login.login_view = "auth.login"
    gerenciador_de_login.login_message = "Faça login para continuar."
    gerenciador_de_login.login_message_category = "erro"
    gerenciador_de_login.user_loader(carregar_usuario)


def _registrar_blueprints(app: Flask) -> None:
    from .routes.alertas import bp as alertas_bp
    from .routes.auth import bp as auth_bp
    from .routes.leituras import bp as leituras_bp
    from .routes.medidores import bp as medidores_bp
    from .routes.painel import bp as painel_bp
    from .routes.setores import bp as setores_bp

    app.register_blueprint(alertas_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(leituras_bp)
    app.register_blueprint(medidores_bp)
    app.register_blueprint(painel_bp)
    app.register_blueprint(setores_bp)
