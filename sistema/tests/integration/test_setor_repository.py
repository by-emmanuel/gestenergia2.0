"""Testes do repositório e do serviço de setores contra o MySQL (issue #16).

Exige o banco de pé:  docker compose up -d db
"""

from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Alerta, Leitura, Medidor, Setor, TipoAlerta
from app.services import setor_service


@pytest.fixture
def contexto(app, banco):
    """Contexto de aplicação com o schema limpo, para o repositório ter sessão."""
    with app.app_context():
        yield


def test_cadastra_e_encontra_o_setor(contexto):
    setor, erros = setor_service.criar(
        {
            "nome": "Produção",
            "descricao": "Linha de produção",
            "limite_consumo_kwh": "122,71",
            "arquivo_modelo": "modelo_consumo_producao.pkl",
            "tem_fator_potencia": True,
        }
    )

    assert erros == []
    assert setor.id is not None
    assert setor.limite_consumo_kwh == Decimal("122.710")
    assert setor.tem_fator_potencia is True
    assert setor.ativo is True


def test_setor_sem_limite_e_sem_modelo_e_aceito(contexto):
    """Regra 10: é o estado dos 4 setores até a issue #44 calcular."""
    setor, erros = setor_service.criar({"nome": "Administrativo"})

    assert erros == []
    assert setor.limite_consumo_kwh is None
    assert setor.arquivo_modelo is None
    assert setor.tem_fator_potencia is False


def test_nome_repetido_e_barrado_pelo_servico(contexto):
    setor_service.criar({"nome": "Utilidades"})

    repetido, erros = setor_service.criar({"nome": "Utilidades"})

    assert repetido is None
    assert any("Já existe um setor" in e for e in erros)


def test_nome_repetido_ignorando_maiusculas(contexto):
    """A colação do MySQL ignora maiúsculas, e o serviço acompanha."""
    setor_service.criar({"nome": "Manutenção"})

    repetido, erros = setor_service.criar({"nome": "MANUTENÇÃO"})

    assert repetido is None
    assert any("Já existe um setor" in e for e in erros)


def test_limite_invalido_nao_chega_ao_banco(contexto):
    setor, erros = setor_service.criar({"nome": "Setor zerado", "limite_consumo_kwh": "0"})

    assert setor is None
    assert any("maior que zero" in e for e in erros)
    assert setor_service.listar() == []


def test_lista_em_ordem_alfabetica(contexto):
    for nome in ("Utilidades", "Administrativo", "Produção"):
        setor_service.criar({"nome": nome})

    assert [s.nome for s in setor_service.listar()] == [
        "Administrativo",
        "Produção",
        "Utilidades",
    ]


def test_lista_apenas_ativos_omite_desativados(contexto):
    ativo, _ = setor_service.criar({"nome": "Ativo"})
    inativo, _ = setor_service.criar({"nome": "Inativo"})
    setor_service.alternar_ativo(inativo.id)

    assert [s.nome for s in setor_service.listar(apenas_ativos=True)] == ["Ativo"]
    assert len(setor_service.listar()) == 2


def test_atualiza_o_limite(contexto):
    setor, _ = setor_service.criar({"nome": "Produção"})

    atualizado, erros = setor_service.atualizar(
        setor.id, {"nome": "Produção", "limite_consumo_kwh": "99,5"}
    )

    assert erros == []
    assert atualizado.limite_consumo_kwh == Decimal("99.500")


def test_limpar_o_limite_devolve_o_setor_ao_estado_sem_alerta(contexto):
    setor, _ = setor_service.criar({"nome": "Produção", "limite_consumo_kwh": "100"})

    atualizado, erros = setor_service.atualizar(
        setor.id, {"nome": "Produção", "limite_consumo_kwh": ""}
    )

    assert erros == []
    assert atualizado.limite_consumo_kwh is None


def test_atualizar_setor_que_nao_existe(contexto):
    setor, erros = setor_service.atualizar(9999, {"nome": "Qualquer"})

    assert setor is None
    assert erros == ["Setor não encontrado."]


def test_conta_os_medidores_do_setor(contexto, sessao):
    setor, _ = setor_service.criar({"nome": "Produção"})
    sessao.add_all(
        [
            Medidor(id_setor=setor.id, codigo="MED-1"),
            Medidor(id_setor=setor.id, codigo="MED-2"),
        ]
    )
    sessao.commit()

    assert setor_service.contar_medidores(setor.id) == 2


# ---------------------------------------------------------------------------
# O critério central: desativar NÃO apaga histórico
# ---------------------------------------------------------------------------


def test_desativar_nao_apaga_medidores_leituras_nem_alertas(contexto, sessao):
    setor, _ = setor_service.criar({"nome": "Produção", "limite_consumo_kwh": "100"})
    medidor = Medidor(id_setor=setor.id, codigo="MED-PROD")
    leitura = Leitura(
        medidor=medidor,
        data_hora=datetime(2018, 1, 1, 0, 15),
        consumo_kwh=Decimal("150"),
        consumo_previsto_kwh=Decimal("150"),
    )
    sessao.add(
        Alerta(
            leitura=leitura,
            tipo=TipoAlerta.CONSUMO_ACIMA_LIMITE,
            valor_observado=Decimal("150"),
            limite_referencia=Decimal("100"),
        )
    )
    sessao.commit()

    desativado, erro = setor_service.alternar_ativo(setor.id)

    assert erro is None
    assert desativado.ativo is False
    # Nada foi apagado: o histórico inteiro continua lá.
    assert sessao.scalar(select(Medidor).where(Medidor.codigo == "MED-PROD")) is not None
    assert len(list(sessao.scalars(select(Leitura)))) == 1
    assert len(list(sessao.scalars(select(Alerta)))) == 1
    # E o setor continua existindo, só marcado como inativo.
    assert sessao.scalar(select(Setor).where(Setor.id == setor.id)) is not None


def test_reativar_devolve_o_setor_ao_uso(contexto):
    setor, _ = setor_service.criar({"nome": "Produção"})
    setor_service.alternar_ativo(setor.id)

    reativado, erro = setor_service.alternar_ativo(setor.id)

    assert erro is None
    assert reativado.ativo is True


def test_alternar_setor_que_nao_existe(contexto):
    setor, erro = setor_service.alternar_ativo(9999)

    assert setor is None
    assert erro == "Setor não encontrado."
