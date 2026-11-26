"""Testes da aplicacao base (issue #9). Sem banco."""

from app.routes import painel


def test_create_app_usa_a_configuracao_de_teste(app):
    assert app.config["TESTING"] is True
    assert app.config["NOME_DO_BANCO"].endswith("_test")


def test_url_do_banco_aponta_para_mysql_com_pymysql(app):
    assert app.config["SQLALCHEMY_DATABASE_URI"].startswith("mysql+pymysql://")


def test_pagina_inicial_responde_em_portugues(cliente):
    resposta = cliente.get("/")

    assert resposta.status_code == 200
    corpo = resposta.get_data(as_text=True)
    assert "GestEnergia" in corpo
    assert "fator de potência" in corpo


def test_pagina_inicial_usa_o_css_local(cliente):
    """Nada de CDN: o CSS e o Chart.js sao servidos pelo proprio sistema."""
    corpo = cliente.get("/").get_data(as_text=True)

    assert "/static/css/estilo.css" in corpo
    assert "cdn" not in corpo.lower()


def test_saude_responde_200_quando_o_banco_conecta(cliente, monkeypatch):
    monkeypatch.setattr(painel, "verificar_banco", lambda url: (True, "8.0.36"))

    resposta = cliente.get("/saude")

    assert resposta.status_code == 200
    corpo = resposta.get_json()
    assert corpo["aplicacao"] == "ok"
    assert corpo["banco"] == "ok"
    assert corpo["banco_detalhe"] == "8.0.36"
    assert corpo["nome_do_banco"].endswith("_test")


def test_saude_responde_503_quando_o_banco_falha(cliente, monkeypatch):
    monkeypatch.setattr(painel, "verificar_banco", lambda url: (False, "OperationalError"))

    resposta = cliente.get("/saude")

    assert resposta.status_code == 503
    assert resposta.get_json()["banco"] == "falhou"


def test_saude_informa_quantos_modelos_estao_carregados(cliente, monkeypatch):
    """Issue #26. Sem isto, um ml/ vazio só apareceria depois de 5 leituras."""
    monkeypatch.setattr(painel, "verificar_banco", lambda url: (True, "8.0.36"))
    monkeypatch.setattr(
        painel.previsao_service, "modelos_carregados", lambda: ["modelo_consumo_producao.pkl"]
    )

    corpo = cliente.get("/saude").get_json()

    assert corpo["modelos"] == 1
    assert corpo["modelos_carregados"] == ["modelo_consumo_producao.pkl"]


def test_saude_sem_modelo_nenhum_continua_respondendo_200(cliente, monkeypatch):
    """Regra 9: a aplicação sobe sem modelo — o /saude denuncia, não derruba."""
    monkeypatch.setattr(painel, "verificar_banco", lambda url: (True, "8.0.36"))
    monkeypatch.setattr(painel.previsao_service, "modelos_carregados", list)

    resposta = cliente.get("/saude")

    assert resposta.status_code == 200
    assert resposta.get_json()["modelos"] == 0
