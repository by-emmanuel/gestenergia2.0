"""Configuracao da aplicacao, lida do .env (issue #9)."""

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent

load_dotenv(RAIZ / ".env")


def _url_do_banco(nome_do_banco: str) -> str:
    """Monta a URL de conexao do SQLAlchemy a partir das variaveis do .env."""
    usuario = os.getenv("MYSQL_USER", "gestenergia")
    senha = os.getenv("MYSQL_PASSWORD", "gestenergia")
    host = os.getenv("MYSQL_HOST", "localhost")
    porta = os.getenv("MYSQL_PORT", "3306")
    return f"mysql+pymysql://{usuario}:{senha}@{host}:{porta}/{nome_do_banco}?charset=utf8mb4"


class Config:
    """Configuracao de desenvolvimento."""

    SECRET_KEY = os.getenv("SECRET_KEY", "chave-de-desenvolvimento-trocar-no-env")

    NOME_DO_BANCO = os.getenv("MYSQL_DATABASE", "gestenergia")
    SQLALCHEMY_DATABASE_URI = _url_do_banco(NOME_DO_BANCO)

    CAMINHO_MODELO = os.getenv("CAMINHO_MODELO", "ml")

    TESTING = False


class ConfigTeste(Config):
    """Configuracao dos testes: usa o banco gestenergia_test."""

    NOME_DO_BANCO = os.getenv("MYSQL_DATABASE_TEST", "gestenergia_test")
    SQLALCHEMY_DATABASE_URI = _url_do_banco(NOME_DO_BANCO)

    TESTING = True
