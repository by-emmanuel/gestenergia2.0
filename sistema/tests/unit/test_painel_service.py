"""Testes das decisões de apresentação do painel sem banco (issue #20).

O que se confere aqui é o que o painel decide por conta própria: a janela de
tempo, a escolha de setor e medidor, e o mapeamento de cor e rótulo por tipo de
alerta — que não pode depender de cor sozinha.
"""

import pytest

from app.models import Medidor, Setor, TipoAlerta
from app.services import painel_service


# ---------------------------------------------------------------------------
# Janela de tempo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("chave, quantidade", [("dia", 96), ("semana", 672), ("mes", 2880)])
def test_cada_janela_cobre_a_quantidade_certa_de_leituras(chave, quantidade):
    """Cadência de 15 minutos: 4 por hora, 96 por dia, 672 por semana."""
    assert painel_service.quantidade_da_janela(chave) == quantidade


@pytest.mark.parametrize("invalida", ["xpto", "", None, "7d"])
def test_janela_invalida_cai_no_padrao(invalida):
    """Query string adulterada não pode virar erro nem tela vazia."""
    assert painel_service.quantidade_da_janela(invalida) == 96


def test_a_janela_padrao_existe_na_lista_oferecida():
    assert painel_service.JANELA_PADRAO in [chave for chave, _, _ in painel_service.JANELAS]


def test_as_janelas_sao_multiplos_da_cadencia_de_15_minutos():
    """96 = 24 h × 4. Se deixar de ser múltiplo, o rótulo mente sobre o período."""
    for _, _, quantidade in painel_service.JANELAS:
        assert quantidade % 96 == 0


# ---------------------------------------------------------------------------
# Escolha de setor e medidor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("vazio", ["", "   ", None])
def test_setor_vazio_significa_todos(vazio, monkeypatch):
    monkeypatch.setattr(painel_service.setor_repository, "buscar_por_id", lambda i: Setor(id=1))

    assert painel_service.escolher_setor(vazio) is None


def test_setor_que_nao_e_numero_cai_em_todos(monkeypatch):
    monkeypatch.setattr(painel_service.setor_repository, "buscar_por_id", lambda i: Setor(id=1))

    assert painel_service.escolher_setor("abc") is None


@pytest.fixture
def medidor_com_dado(monkeypatch):
    """Diz qual medidor tem a leitura mais recente, sem tocar no banco."""

    def configurar(id_medidor):
        monkeypatch.setattr(
            painel_service.leitura_repository,
            "medidor_com_leitura_mais_recente",
            lambda ids: id_medidor,
        )

    return configurar


def test_o_painel_abre_no_medidor_que_tem_dado(medidor_com_dado):
    """E nao no primeiro em ordem alfabetica, que pode estar sem leitura.

    Com os 4 medidores do banco.sql o primeiro em ordem e o MED-ADMI: o painel
    abria vazio tendo dado no medidor ao lado.
    """
    primeiro = Medidor(id=1, codigo="MED-A", id_setor=1)
    segundo = Medidor(id=2, codigo="MED-B", id_setor=1)
    medidor_com_dado(2)

    assert painel_service.escolher_medidor(None, [primeiro, segundo]) is segundo


def test_sem_leitura_em_nenhum_medidor_abre_no_primeiro(medidor_com_dado):
    primeiro = Medidor(id=1, codigo="MED-A", id_setor=1)
    segundo = Medidor(id=2, codigo="MED-B", id_setor=1)
    medidor_com_dado(None)

    assert painel_service.escolher_medidor(None, [primeiro, segundo]) is primeiro


def test_o_medidor_escolhido_e_respeitado():
    primeiro = Medidor(id=1, codigo="MED-A", id_setor=1)
    segundo = Medidor(id=2, codigo="MED-B", id_setor=1)

    assert painel_service.escolher_medidor("2", [primeiro, segundo]) is segundo


def test_medidor_fora_da_lista_cai_no_padrao(medidor_com_dado):
    """Trocar o setor invalida o medidor anterior: o painel não pode quebrar."""
    primeiro = Medidor(id=1, codigo="MED-A", id_setor=1)
    medidor_com_dado(None)

    assert painel_service.escolher_medidor("99", [primeiro]) is primeiro


def test_sem_medidor_nenhum_devolve_none(medidor_com_dado):
    medidor_com_dado(None)

    assert painel_service.escolher_medidor("1", []) is None


def test_serie_sem_medidor_vem_vazia_e_nao_quebra():
    serie = painel_service.serie(None, 96)

    assert serie["rotulos"] == []
    assert serie["real"] == []
    assert serie["tem_previsto"] is False


def test_tabela_sem_medidor_vem_vazia():
    assert painel_service.tabela(None, 96) == []


# ---------------------------------------------------------------------------
# Cor e rótulo por tipo de alerta
# ---------------------------------------------------------------------------


def test_todo_tipo_de_alerta_tem_cor_e_rotulo():
    """Um tipo novo sem cor ou rótulo quebraria o painel: o teste tranca isso."""
    for tipo in TipoAlerta:
        assert tipo in painel_service.CORES_POR_TIPO_DE_ALERTA
        assert tipo in painel_service.ROTULOS_DE_TIPO
        assert painel_service.ROTULOS_DE_TIPO[tipo].strip()


def test_as_cores_dos_tipos_sao_diferentes_entre_si():
    cores = set(painel_service.CORES_POR_TIPO_DE_ALERTA.values())

    assert len(cores) == len(TipoAlerta)


def test_o_rotulo_nunca_e_so_a_cor():
    """Cor sozinha não identifica nada em preto e branco nem para quem não a distingue."""
    for tipo in TipoAlerta:
        rotulo = painel_service.ROTULOS_DE_TIPO[tipo]
        assert not rotulo.startswith("#")
        assert len(rotulo) > 5


def test_o_alerta_de_consumo_usa_a_cor_da_serie_prevista():
    """É a série prevista que dispara esse alerta, então a cor é a mesma de propósito."""
    assert (
        painel_service.CORES_POR_TIPO_DE_ALERTA[TipoAlerta.CONSUMO_ACIMA_LIMITE]
        == painel_service.COR_PREVISTO
    )


def test_as_duas_series_do_grafico_tem_cores_diferentes():
    assert painel_service.COR_REAL != painel_service.COR_PREVISTO


@pytest.mark.parametrize(
    "cor",
    [
        painel_service.COR_REAL,
        painel_service.COR_PREVISTO,
        *painel_service.CORES_POR_TIPO_DE_ALERTA.values(),
    ],
)
def test_as_cores_sao_hexadecimais_de_6_digitos(cor):
    assert len(cor) == 7 and cor.startswith("#")
    int(cor[1:], 16)
