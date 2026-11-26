"""Testes do repositório e do serviço de leituras contra o MySQL (issue #18).

Exige o banco de pé:  docker compose up -d db
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Leitura
from app.services import leitura_service, medidor_service, setor_service


@pytest.fixture
def contexto(app, banco):
    with app.app_context():
        yield


@pytest.fixture
def medidor(contexto):
    setor, erros = setor_service.criar({"nome": "Produção", "tem_fator_potencia": True})
    assert erros == []
    medidor, erros = medidor_service.criar({"codigo": "MED-PROD", "id_setor": str(setor.id)})
    assert erros == []
    return medidor


def formulario(medidor, **campos):
    dados = {
        "id_medidor": str(medidor.id),
        "data_hora": "2018-01-01T00:15",
        "consumo_kwh": "3,17",
        "fator_potencia": "",
    }
    dados.update(campos)
    return dados


def test_registra_a_leitura(medidor):
    leitura, erros = leitura_service.registrar(formulario(medidor, fator_potencia="0,95"))

    assert erros == []
    assert leitura.id is not None
    assert leitura.data_hora == datetime(2018, 1, 1, 0, 15)
    assert leitura.consumo_kwh == Decimal("3.170")
    assert leitura.fator_potencia == Decimal("0.950")
    # Regra 4: sem 4 leituras anteriores, nasce sem previsão.
    assert leitura.consumo_previsto_kwh is None


def test_leitura_sem_fator_de_potencia_e_aceita(medidor):
    """Regra 1: hoje só a Produção tem o dado, e a falta dele não é erro."""
    leitura, erros = leitura_service.registrar(formulario(medidor, fator_potencia=""))

    assert erros == []
    assert leitura.fator_potencia is None


# ---------------------------------------------------------------------------
# Regra 3: duplicidade, no serviço E no banco
# ---------------------------------------------------------------------------


def test_leitura_duplicada_e_recusada_pelo_servico(medidor):
    leitura_service.registrar(formulario(medidor))

    repetida, erros = leitura_service.registrar(formulario(medidor))

    assert repetida is None
    assert len(erros) == 1
    assert "01/01/2018 às 00:15" in erros[0]
    assert leitura_service.contar() == 1


def test_a_chave_unica_do_banco_fecha_a_corrida_que_o_servico_perderia(medidor, monkeypatch):
    """Os dois mecanismos são necessários, e este testa o segundo.

    Dois envios simultâneos passam pela validação ao mesmo tempo (nenhum vê a
    leitura do outro, que ainda não foi gravada). Aqui a validação é forçada a
    dizer que não há duplicata, e a chave única do banco tem de recusar — com a
    MESMA mensagem do caminho normal, não com erro 500.
    """
    leitura_service.registrar(formulario(medidor))
    monkeypatch.setattr(leitura_service.leitura_repository, "existe", lambda m, d: False)

    repetida, erros = leitura_service.registrar(formulario(medidor))

    assert repetida is None
    assert len(erros) == 1
    assert "uma única leitura por data e hora" in erros[0]
    assert leitura_service.contar() == 1

    # E a sessão continua utilizável: sem o rollback ela ficaria em "pending
    # rollback" e o resto da requisição falharia, mesmo com o erro tratado.
    seguinte, erros = leitura_service.registrar(
        formulario(medidor, data_hora="2018-01-01T00:30")
    )
    assert erros == []
    assert seguinte is not None
    assert leitura_service.contar() == 2


def test_mesmo_instante_em_medidores_diferentes_e_permitido(medidor, contexto):
    """A chave única é (medidor, data_hora): outro medidor no mesmo instante vale."""
    outro, erros = medidor_service.criar(
        {"codigo": "MED-OUTRO", "id_setor": str(medidor.id_setor)}
    )
    assert erros == []

    leitura_service.registrar(formulario(medidor))
    segunda, erros = leitura_service.registrar(formulario(outro))

    assert erros == []
    assert segunda is not None
    assert leitura_service.contar() == 2


def test_o_mesmo_medidor_em_instantes_diferentes_e_permitido(medidor):
    leitura_service.registrar(formulario(medidor, data_hora="2018-01-01T00:15"))
    segunda, erros = leitura_service.registrar(formulario(medidor, data_hora="2018-01-01T00:30"))

    assert erros == []
    assert segunda is not None


def test_medidor_desativado_nao_aceita_leitura(medidor):
    medidor_service.alternar_ativo(medidor.id)

    leitura, erros = leitura_service.registrar(formulario(medidor))

    assert leitura is None
    assert any("está desativado" in e for e in erros)
    assert leitura_service.contar() == 0


def test_fator_acima_de_1_nao_chega_ao_banco(medidor):
    """Regra 6: o percentual da base não entra cru."""
    leitura, erros = leitura_service.registrar(formulario(medidor, fator_potencia="73,21"))

    assert leitura is None
    assert any("de 0 a 1" in e for e in erros)
    assert leitura_service.contar() == 0


def test_consumo_negativo_nao_chega_ao_banco(medidor):
    leitura, erros = leitura_service.registrar(formulario(medidor, consumo_kwh="-1"))

    assert leitura is None
    assert leitura_service.contar() == 0


# ---------------------------------------------------------------------------
# Regra 4: as 4 leituras anteriores
# ---------------------------------------------------------------------------


def registrar_sequencia(medidor, quantidade: int) -> None:
    """Registra N leituras de 15 em 15 minutos, como as bases medem."""
    inicio = datetime(2018, 1, 1, 0, 15)
    for i in range(quantidade):
        instante = inicio + timedelta(minutes=15 * i)
        leitura, erros = leitura_service.registrar(
            formulario(
                medidor,
                data_hora=instante.strftime("%Y-%m-%dT%H:%M"),
                consumo_kwh=str(10 + i),
            )
        )
        assert erros == [], erros


@pytest.mark.parametrize("quantidade, esperado", [(0, False), (3, False), (4, True), (5, True)])
def test_so_da_para_prever_com_4_leituras_anteriores(medidor, quantidade, esperado):
    registrar_sequencia(medidor, quantidade)

    assert leitura_service.tem_leituras_para_prever(medidor.id) is esperado


def test_as_ultimas_leituras_vem_da_mais_nova_para_a_mais_antiga(medidor):
    """É a ordem que o PrevisaoService precisa para montar lag_1 a lag_4 (#26)."""
    registrar_sequencia(medidor, 5)

    ultimas = leitura_service.leitura_repository.ultimas_do_medidor(medidor.id, 4)

    assert [u.data_hora.strftime("%H:%M") for u in ultimas] == ["01:15", "01:00", "00:45", "00:30"]
    # lag_1 é a leitura imediatamente anterior.
    assert ultimas[0].consumo_kwh == Decimal("14.000")


# ---------------------------------------------------------------------------
# Listagem
# ---------------------------------------------------------------------------


def test_lista_as_recentes_primeiro(medidor):
    registrar_sequencia(medidor, 3)

    recentes = leitura_service.listar_recentes()

    assert [r.data_hora.strftime("%H:%M") for r in recentes] == ["00:45", "00:30", "00:15"]
    # O medidor e o setor vêm carregados, sem consulta por linha.
    assert recentes[0].medidor.setor.nome == "Produção"


def test_a_lista_respeita_o_limite(medidor):
    registrar_sequencia(medidor, 6)

    assert len(leitura_service.listar_recentes(limite=4)) == 4
    assert leitura_service.contar() == 6


def test_o_banco_tambem_recusa_duplicidade_por_insercao_direta(medidor, sessao):
    """Prova que uq_leitura_medidor_data_hora está no schema dos models."""
    from sqlalchemy.exc import IntegrityError

    quando = datetime(2018, 1, 1, 0, 15)
    sessao.add(Leitura(id_medidor=medidor.id, data_hora=quando, consumo_kwh=Decimal("1")))
    sessao.commit()
    sessao.add(Leitura(id_medidor=medidor.id, data_hora=quando, consumo_kwh=Decimal("2")))

    with pytest.raises(IntegrityError):
        sessao.commit()
    sessao.rollback()
    assert len(list(sessao.scalars(select(Leitura)))) == 1
