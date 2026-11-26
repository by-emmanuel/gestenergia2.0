"""Testes do repositório e do serviço de medidores contra o MySQL (issue #17).

Exige o banco de pé:  docker compose up -d db
"""

from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Leitura, Medidor
from app.services import medidor_service, setor_service


@pytest.fixture
def contexto(app, banco):
    with app.app_context():
        yield


@pytest.fixture
def producao(contexto):
    setor, erros = setor_service.criar({"nome": "Produção"})
    assert erros == []
    return setor


@pytest.fixture
def utilidades(contexto):
    setor, erros = setor_service.criar({"nome": "Utilidades"})
    assert erros == []
    return setor


def test_cadastra_e_encontra_o_medidor(producao):
    medidor, erros = medidor_service.criar(
        {"codigo": "med-prod", "descricao": "Medidor principal", "id_setor": str(producao.id)}
    )

    assert erros == []
    assert medidor.id is not None
    assert medidor.codigo == "MED-PROD"  # gravado em maiúsculas
    assert medidor.ativo is True
    assert medidor.setor.nome == "Produção"


def test_codigo_repetido_e_barrado_pelo_servico(producao):
    medidor_service.criar({"codigo": "MED-PROD", "id_setor": str(producao.id)})

    repetido, erros = medidor_service.criar({"codigo": "MED-PROD", "id_setor": str(producao.id)})

    assert repetido is None
    assert any("Já existe um medidor" in e for e in erros)


def test_codigo_repetido_ignorando_maiusculas(producao):
    medidor_service.criar({"codigo": "MED-PROD", "id_setor": str(producao.id)})

    repetido, erros = medidor_service.criar({"codigo": "med-prod", "id_setor": str(producao.id)})

    assert repetido is None
    assert any("Já existe um medidor" in e for e in erros)


def test_nao_cadastra_em_setor_desativado(producao):
    setor_service.alternar_ativo(producao.id)

    medidor, erros = medidor_service.criar({"codigo": "MED-X", "id_setor": str(producao.id)})

    assert medidor is None
    assert any("está desativado" in e for e in erros)


def test_move_o_medidor_de_setor(producao, utilidades):
    medidor, _ = medidor_service.criar({"codigo": "MED-X", "id_setor": str(producao.id)})

    atualizado, erros = medidor_service.atualizar(
        medidor.id, {"codigo": "MED-X", "id_setor": str(utilidades.id)}
    )

    assert erros == []
    assert atualizado.setor.nome == "Utilidades"


def test_nao_move_para_setor_desativado(producao, utilidades):
    medidor, _ = medidor_service.criar({"codigo": "MED-X", "id_setor": str(producao.id)})
    setor_service.alternar_ativo(utilidades.id)

    atualizado, erros = medidor_service.atualizar(
        medidor.id, {"codigo": "MED-X", "id_setor": str(utilidades.id)}
    )

    assert atualizado is None
    assert any("está desativado" in e for e in erros)


def test_edita_medidor_cujo_setor_foi_desativado_depois(producao):
    """Desativar setor não apaga histórico: o medidor continua editável."""
    medidor, _ = medidor_service.criar({"codigo": "MED-X", "id_setor": str(producao.id)})
    setor_service.alternar_ativo(producao.id)

    atualizado, erros = medidor_service.atualizar(
        medidor.id,
        {"codigo": "MED-X", "descricao": "ainda em uso", "id_setor": str(producao.id)},
    )

    assert erros == []
    assert atualizado.descricao == "ainda em uso"


def test_lista_ordenada_por_setor_e_depois_por_codigo(producao, utilidades):
    for codigo, setor in (
        ("MED-B", producao),
        ("MED-A", producao),
        ("MED-C", utilidades),
    ):
        medidor_service.criar({"codigo": codigo, "id_setor": str(setor.id)})

    # "Produção" vem antes de "Utilidades"; dentro do setor, por código.
    assert [m.codigo for m in medidor_service.listar()] == ["MED-A", "MED-B", "MED-C"]


def test_lista_apenas_ativos_omite_desativados(producao):
    ativo, _ = medidor_service.criar({"codigo": "MED-ATIVO", "id_setor": str(producao.id)})
    inativo, _ = medidor_service.criar({"codigo": "MED-INATIVO", "id_setor": str(producao.id)})
    medidor_service.alternar_ativo(inativo.id)

    assert [m.codigo for m in medidor_service.listar(apenas_ativos=True)] == ["MED-ATIVO"]
    assert len(medidor_service.listar()) == 2


def test_conta_as_leituras_do_medidor(producao, sessao):
    medidor, _ = medidor_service.criar({"codigo": "MED-X", "id_setor": str(producao.id)})
    sessao.add_all(
        [
            Leitura(id_medidor=medidor.id, data_hora=datetime(2018, 1, 1, 0, 15), consumo_kwh=Decimal("10")),
            Leitura(id_medidor=medidor.id, data_hora=datetime(2018, 1, 1, 0, 30), consumo_kwh=Decimal("11")),
        ]
    )
    sessao.commit()

    assert medidor_service.contar_leituras(medidor.id) == 2


def test_desativar_nao_apaga_leituras(producao, sessao):
    medidor, _ = medidor_service.criar({"codigo": "MED-X", "id_setor": str(producao.id)})
    sessao.add(
        Leitura(id_medidor=medidor.id, data_hora=datetime(2018, 1, 1, 0, 15), consumo_kwh=Decimal("10"))
    )
    sessao.commit()

    desativado, erro = medidor_service.alternar_ativo(medidor.id)

    assert erro is None
    assert desativado.ativo is False
    assert len(list(sessao.scalars(select(Leitura)))) == 1
    assert sessao.scalar(select(Medidor).where(Medidor.id == medidor.id)) is not None


def test_nao_reativa_medidor_de_setor_desativado(producao):
    """Reativar aqui deixaria um medidor ativo pendurado num setor inativo."""
    medidor, _ = medidor_service.criar({"codigo": "MED-X", "id_setor": str(producao.id)})
    medidor_service.alternar_ativo(medidor.id)
    setor_service.alternar_ativo(producao.id)

    reativado, erro = medidor_service.alternar_ativo(medidor.id)

    assert reativado is None
    assert "Reative o setor" in erro


def test_atualizar_medidor_que_nao_existe(contexto):
    medidor, erros = medidor_service.atualizar(9999, {"codigo": "MED-X", "id_setor": "1"})

    assert medidor is None
    assert erros == ["Medidor não encontrado."]


def test_alternar_medidor_que_nao_existe(contexto):
    medidor, erro = medidor_service.alternar_ativo(9999)

    assert medidor is None
    assert erro == "Medidor não encontrado."
