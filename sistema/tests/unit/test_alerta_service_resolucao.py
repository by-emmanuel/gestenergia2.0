"""Testes da resolução de alertas sem banco (issue #28).

O repositório é trocado por dublês: o que se testa aqui é a regra — observação
obrigatória, alerta já resolvido, o que fica gravado — e não a consulta.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from app.models import Alerta, StatusAlerta, TipoAlerta, Usuario
from app.services import alerta_service


@pytest.fixture
def alerta_aberto(monkeypatch):
    """Instala um alerta ABERTO no repositório e devolve o objeto."""
    alerta = Alerta(
        id=7,
        id_leitura=1,
        tipo=TipoAlerta.FATOR_POTENCIA_BAIXO,
        valor_observado=Decimal("0.730"),
        limite_referencia=Decimal("0.920"),
        status=StatusAlerta.ABERTO,
    )
    monkeypatch.setattr(alerta_service.alerta_repository, "buscar_por_id", lambda i: alerta)
    monkeypatch.setattr(alerta_service.alerta_repository, "salvar", lambda a: a)
    return alerta


def gestor():
    return Usuario(id=3, nome="Gestor de Energia", email="gestor@gestenergia.local")


# ---------------------------------------------------------------------------
# O caminho feliz — critérios da #28
# ---------------------------------------------------------------------------


def test_resolver_muda_o_status(alerta_aberto):
    alerta, erros = alerta_service.resolver(7, "Capacitor religado", gestor())

    assert erros == []
    assert alerta.status == StatusAlerta.RESOLVIDO


def test_resolver_guarda_quem_quando_e_o_que_foi_feito(alerta_aberto):
    """É o que torna o alerta auditável depois."""
    antes = datetime.now().replace(microsecond=0)

    alerta, _ = alerta_service.resolver(7, "Capacitor religado", gestor())

    assert alerta.observacao_resolucao == "Capacitor religado"
    assert alerta.id_usuario_resolucao == 3
    assert alerta.resolvido_em >= antes
    assert alerta.resolvido_em.microsecond == 0  # a coluna é DATETIME sem fração


def test_a_observacao_e_limpa_das_bordas(alerta_aberto):
    alerta, _ = alerta_service.resolver(7, "   Capacitor religado   ", gestor())

    assert alerta.observacao_resolucao == "Capacitor religado"


# ---------------------------------------------------------------------------
# Observação obrigatória — critério da #28 e CHECK do banco
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("observacao", ["", "   ", None, "ok", "  a  "])
def test_observacao_vazia_ou_curta_demais_recusa(alerta_aberto, observacao):
    alerta, erros = alerta_service.resolver(7, observacao, gestor())

    assert alerta is None
    assert "Escreva o que foi feito" in erros[0]
    assert alerta_aberto.status == StatusAlerta.ABERTO  # nada mudou


def test_observacao_longa_demais_recusa(alerta_aberto):
    """A coluna é VARCHAR(500): recusar aqui dá mensagem melhor que o erro do banco."""
    alerta, erros = alerta_service.resolver(7, "x" * 501, gestor())

    assert alerta is None
    assert "500 caracteres" in erros[0]


def test_observacao_no_limite_e_aceita(alerta_aberto):
    alerta, erros = alerta_service.resolver(7, "x" * 500, gestor())

    assert erros == []
    assert len(alerta.observacao_resolucao) == 500


# ---------------------------------------------------------------------------
# Casos que não podem acontecer duas vezes
# ---------------------------------------------------------------------------


def test_alerta_ja_resolvido_recusa(alerta_aberto):
    """Dois cliques no mesmo botão não podem reescrever quem resolveu."""
    alerta_aberto.status = StatusAlerta.RESOLVIDO

    alerta, erros = alerta_service.resolver(7, "Capacitor religado", gestor())

    assert alerta is None
    assert erros == ["Este alerta já foi resolvido."]


def test_alerta_inexistente_recusa(monkeypatch):
    monkeypatch.setattr(alerta_service.alerta_repository, "buscar_por_id", lambda i: None)

    alerta, erros = alerta_service.resolver(999, "Capacitor religado", gestor())

    assert alerta is None
    assert erros == ["Alerta não encontrado."]


# ---------------------------------------------------------------------------
# Os filtros da listagem
# ---------------------------------------------------------------------------


@pytest.fixture
def espiao(monkeypatch):
    """Guarda com que argumentos o repositório foi chamado."""
    chamadas = {}

    def listar(**kwargs):
        chamadas.update(kwargs)
        return [], 0

    monkeypatch.setattr(alerta_service.alerta_repository, "listar", listar)
    monkeypatch.setattr(alerta_service.alerta_repository, "contar_por_tipo_e_status", dict)
    return chamadas


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("CONSUMO_ACIMA_LIMITE", TipoAlerta.CONSUMO_ACIMA_LIMITE),
        ("FATOR_POTENCIA_BAIXO", TipoAlerta.FATOR_POTENCIA_BAIXO),
        ("", None),
        (None, None),
        ("INVENTADO", None),  # URL editada à mão não pode quebrar a tela
    ],
)
def test_o_filtro_de_tipo_vira_enum(espiao, texto, esperado):
    alerta_service.listar(tipo=texto)

    assert espiao["tipo"] == esperado


@pytest.mark.parametrize(
    "texto, esperado",
    [("ABERTO", StatusAlerta.ABERTO), ("RESOLVIDO", StatusAlerta.RESOLVIDO), ("xpto", None)],
)
def test_o_filtro_de_status_vira_enum(espiao, texto, esperado):
    alerta_service.listar(status=texto)

    assert espiao["status"] == esperado


def test_pagina_zero_ou_negativa_vira_a_primeira(espiao):
    """Outra URL editada à mão: offset negativo seria erro de SQL."""
    for pedida in (0, -1, -999):
        alerta_service.listar(pagina=pedida)
        assert espiao["pagina"] == 1


def test_a_ultima_pagina_sai_da_divisao_para_cima(monkeypatch):
    monkeypatch.setattr(
        alerta_service.alerta_repository, "listar", lambda **k: ([], 332)
    )
    monkeypatch.setattr(alerta_service.alerta_repository, "contar_por_tipo_e_status", dict)

    pagina = alerta_service.listar()

    # 332 alertas, 25 por página -> 14 páginas (13 cheias e uma com 7).
    assert pagina["ultima_pagina"] == 14
    assert pagina["total"] == 332


def test_sem_nenhum_alerta_ainda_ha_uma_pagina(monkeypatch):
    """Zero dividido por 25 é zero, mas a tela não pode dizer 'página 1 de 0'."""
    monkeypatch.setattr(alerta_service.alerta_repository, "listar", lambda **k: ([], 0))
    monkeypatch.setattr(alerta_service.alerta_repository, "contar_por_tipo_e_status", dict)

    assert alerta_service.listar()["ultima_pagina"] == 1
