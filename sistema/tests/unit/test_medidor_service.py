"""Testes das regras de medidor sem banco (issue #17).

A validação consulta os repositórios de medidor e de setor, então os dois são
trocados por dublês.
"""

import pytest

from app.models import Medidor, Setor
from app.services import medidor_service


@pytest.fixture
def mundo(monkeypatch):
    """Monta um cenário: que setores existem e que códigos já estão em uso."""

    def configurar(setores=(), medidores=()):
        por_id = {s.id: s for s in setores}
        por_codigo = {m.codigo.upper(): m for m in medidores}
        monkeypatch.setattr(
            medidor_service.setor_repository, "buscar_por_id", lambda i: por_id.get(i)
        )
        monkeypatch.setattr(
            medidor_service.setor_repository,
            "listar",
            lambda apenas_ativos=False: [s for s in setores if s.ativo or not apenas_ativos],
        )
        monkeypatch.setattr(
            medidor_service.medidor_repository,
            "buscar_por_codigo",
            lambda c: por_codigo.get((c or "").upper()),
        )

    return configurar


ATIVO = Setor(id=1, nome="Produção", ativo=True)
DESATIVADO = Setor(id=2, nome="Antigo", ativo=False)


# ---------------------------------------------------------------------------
# Critério 1: código único
# ---------------------------------------------------------------------------


def test_formulario_minimo_valido_passa(mundo):
    mundo(setores=[ATIVO])

    assert medidor_service.validar({"codigo": "MED-PROD", "id_setor": "1"}) == []


def test_codigo_e_obrigatorio(mundo):
    mundo(setores=[ATIVO])

    erros = medidor_service.validar({"codigo": "   ", "id_setor": "1"})

    assert "O código do medidor é obrigatório." in erros


def test_codigo_repetido_e_recusado(mundo):
    mundo(setores=[ATIVO], medidores=[Medidor(id=9, codigo="MED-PROD", id_setor=1)])

    erros = medidor_service.validar({"codigo": "MED-PROD", "id_setor": "1"})

    assert any("Já existe um medidor" in e for e in erros)


def test_codigo_repetido_ignorando_maiusculas(mundo):
    """A colação do MySQL ignora maiúsculas, então o serviço acompanha."""
    mundo(setores=[ATIVO], medidores=[Medidor(id=9, codigo="MED-PROD", id_setor=1)])

    erros = medidor_service.validar({"codigo": "med-prod", "id_setor": "1"})

    assert any("Já existe um medidor" in e for e in erros)


def test_na_edicao_o_medidor_nao_acusa_codigo_repetido_contra_si_mesmo(mundo):
    proprio = Medidor(id=9, codigo="MED-PROD", id_setor=1)
    mundo(setores=[ATIVO], medidores=[proprio])

    erros = medidor_service.validar({"codigo": "MED-PROD", "id_setor": "1"}, medidor=proprio)

    assert erros == []


def test_codigo_longo_demais_e_recusado(mundo):
    mundo(setores=[ATIVO])

    erros = medidor_service.validar({"codigo": "M" * 61, "id_setor": "1"})

    assert any("no máximo 60" in e for e in erros)


# ---------------------------------------------------------------------------
# Critério 2: medidor sempre ligado a um setor ativo
# ---------------------------------------------------------------------------


def test_setor_e_obrigatorio(mundo):
    mundo(setores=[ATIVO])

    erros = medidor_service.validar({"codigo": "MED-X", "id_setor": ""})

    assert "Escolha o setor do medidor." in erros


def test_setor_que_nao_e_numero_e_recusado(mundo):
    mundo(setores=[ATIVO])

    erros = medidor_service.validar({"codigo": "MED-X", "id_setor": "abc"})

    assert "Setor inválido." in erros


def test_setor_que_nao_existe_e_recusado(mundo):
    mundo(setores=[ATIVO])

    erros = medidor_service.validar({"codigo": "MED-X", "id_setor": "999"})

    assert "Setor não encontrado." in erros


def test_nao_cadastra_medidor_em_setor_desativado(mundo):
    mundo(setores=[ATIVO, DESATIVADO])

    erros = medidor_service.validar({"codigo": "MED-X", "id_setor": "2"})

    assert any("está desativado" in e for e in erros)


def test_nao_move_medidor_para_setor_desativado(mundo):
    """Vínculo NOVO para setor desativado é barrado, mesmo na edição."""
    proprio = Medidor(id=9, codigo="MED-X", id_setor=1)
    mundo(setores=[ATIVO, DESATIVADO], medidores=[proprio])

    erros = medidor_service.validar({"codigo": "MED-X", "id_setor": "2"}, medidor=proprio)

    assert any("está desativado" in e for e in erros)


def test_mantem_o_vinculo_com_setor_que_foi_desativado_depois(mundo):
    """Se não fosse assim, desativar um setor tornaria os medidores ineditáveis.

    Desativar setor não apaga histórico (issue #16), então o vínculo antigo é
    preservado — só não se cria vínculo novo.
    """
    proprio = Medidor(id=9, codigo="MED-X", id_setor=2)
    mundo(setores=[ATIVO, DESATIVADO], medidores=[proprio])

    erros = medidor_service.validar(
        {"codigo": "MED-X", "descricao": "nova descrição", "id_setor": "2"}, medidor=proprio
    )

    assert erros == []


# ---------------------------------------------------------------------------
# Escolha de setor no formulário
# ---------------------------------------------------------------------------


def test_o_formulario_de_cadastro_oferece_so_setores_ativos(mundo):
    mundo(setores=[ATIVO, DESATIVADO])

    assert medidor_service.setores_para_escolha() == [ATIVO]


def test_a_edicao_tambem_oferece_o_setor_atual_mesmo_desativado(mundo):
    mundo(setores=[ATIVO, DESATIVADO])
    medidor = Medidor(id=9, codigo="MED-X", id_setor=2)
    medidor.setor = DESATIVADO

    escolhas = medidor_service.setores_para_escolha(medidor)

    assert ATIVO in escolhas
    assert DESATIVADO in escolhas


def test_a_edicao_nao_duplica_o_setor_atual_quando_ele_esta_ativo(mundo):
    mundo(setores=[ATIVO, DESATIVADO])
    medidor = Medidor(id=9, codigo="MED-X", id_setor=1)
    medidor.setor = ATIVO

    assert medidor_service.setores_para_escolha(medidor) == [ATIVO]


# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "digitado, gravado",
    [("med-prod", "MED-PROD"), ("  MED-UTIL  ", "MED-UTIL"), ("Med-Admi", "MED-ADMI")],
)
def test_o_codigo_e_gravado_em_maiusculas_e_sem_espacos(digitado, gravado):
    medidor = medidor_service._aplicar(Medidor(), {"codigo": digitado, "id_setor": "1"})

    assert medidor.codigo == gravado


def test_descricao_vazia_vira_none():
    medidor = medidor_service._aplicar(Medidor(), {"codigo": "MED-X", "descricao": "  ", "id_setor": "1"})

    assert medidor.descricao is None
