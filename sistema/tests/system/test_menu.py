"""Menu do topo: o que o visitante ve e a chegada dos itens apos entrar.

Exige o banco de pe:  docker compose up -d db
"""

from tests.conftest import SENHA_GESTOR

ITENS_RESTRITOS = ("/painel", "/setores", "/medidores", "/leituras", "/alertas")
# Prefixo, sem fechar as aspas: algumas rotas terminam com barra (/setores/).
ITENS_DO_MENU = ('href="/"', *(f'href="{c}' for c in ITENS_RESTRITOS))


def menu_do(corpo: str) -> str:
    """Recorta so o <nav class="menu"> do HTML."""
    inicio = corpo.index('<nav class="menu"')
    return corpo[inicio:corpo.index("</nav>", inicio)]


def test_visitante_nao_tem_menu_so_os_botoes_de_acesso(cliente, banco):
    corpo = cliente.get("/").get_data(as_text=True)
    topo = corpo[corpo.index('<header class="topo'):corpo.index("</header>")]

    assert '<nav class="menu"' not in topo
    for caminho in ITENS_RESTRITOS:
        assert f'href="{caminho}' not in topo
    # O logo leva ao inicio; os botoes levam ao cadastro e ao login.
    assert 'class="marca" href="/"' in topo
    assert 'href="/cadastro"' in topo
    assert 'href="/login"' in topo


def test_primeira_pagina_apos_o_login_anima_os_itens(cliente, usuarios):
    resposta = cliente.post(
        "/login",
        data={"email": "gestor@gestenergia.local", "senha": SENHA_GESTOR},
        follow_redirects=True,
    )

    corpo = resposta.get_data(as_text=True)
    assert "topo-revelar" in corpo
    menu = menu_do(corpo)
    for item in ITENS_DO_MENU:
        assert item in menu


def test_animacao_roda_uma_vez_so(cliente, usuarios):
    cliente.post(
        "/login",
        data={"email": "gestor@gestenergia.local", "senha": SENHA_GESTOR},
        follow_redirects=True,
    )

    segunda = cliente.get("/").get_data(as_text=True)

    assert "topo-revelar" not in segunda
    # Os itens continuam la, so sem animacao.
    assert 'href="/painel"' in menu_do(segunda)


def test_cadastro_tambem_anima_os_itens(cliente, banco):
    resposta = cliente.post(
        "/cadastro",
        data={
            "nome": "Nova Pessoa",
            "email": "nova@gestenergia.local",
            "senha": "senha-forte-123",
            "confirmacao": "senha-forte-123",
        },
        follow_redirects=True,
    )

    assert "topo-revelar" in resposta.get_data(as_text=True)


def test_login_que_falha_nao_anima(cliente, usuarios):
    resposta = cliente.post(
        "/login", data={"email": "gestor@gestenergia.local", "senha": "errada"}
    )

    assert "topo-revelar" not in resposta.get_data(as_text=True)
