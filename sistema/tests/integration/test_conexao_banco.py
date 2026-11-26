"""Teste de conexao real com o MySQL de teste (issues #8 e #9).

Exige o banco de pe:  docker compose up -d db

Desde a issue #8 o verificar_banco recebe o motor da aplicacao, criado uma unica
vez no create_app(), em vez de uma URL. A fixture `motor` (tests/conftest.py) ja
pula o teste quando o MySQL esta fora do ar.
"""

from app.banco import sessao
from app.services.saude_service import verificar_banco


def test_conecta_no_banco_de_teste(motor):
    conectou, detalhe = verificar_banco(motor)

    assert conectou, f"nao conectou: {detalhe}"
    assert detalhe.startswith("8."), f"esperado MySQL 8, veio {detalhe}"


def test_rota_de_saude_responde_200_com_o_banco_de_pe(cliente, motor):
    resposta = cliente.get("/saude")

    assert resposta.status_code == 200
    corpo = resposta.get_json()
    assert corpo["banco"] == "ok"
    assert corpo["nome_do_banco"].endswith("_test")


def test_a_sessao_da_requisicao_e_a_mesma_dentro_do_contexto(app, motor):
    """A sessao e por requisicao: duas chamadas no mesmo contexto dao a mesma."""
    with app.app_context():
        primeira = sessao()
        segunda = sessao()

        assert primeira is segunda


def test_cada_contexto_recebe_a_sua_propria_sessao(app, motor):
    with app.app_context():
        de_um_contexto = sessao()
    with app.app_context():
        de_outro_contexto = sessao()

    assert de_um_contexto is not de_outro_contexto
