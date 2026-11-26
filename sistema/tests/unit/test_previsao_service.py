"""Testes do PrevisaoService sem banco e sem os .pkl de verdade (issue #26).

Os modelos são trocados por dublês com `predict`, porque o que se testa aqui é a
regra — quando prever, com que atributos, o que devolver quando não dá — e não a
qualidade da previsão, que é medida no notebook.

Casos de borda obrigatórios pelo CLAUDE.md cobertos aqui: **menos de 4 leituras**
e previsão nunca negativa (regras 4 e 5).
"""

from datetime import datetime
from decimal import Decimal

import pytest

from app.models import Leitura, Medidor, Setor
from app.services import previsao_service


class ModeloFalso:
    """Dublê de pipeline: guarda o que recebeu e devolve o que mandarem."""

    def __init__(self, devolve=10.0):
        self.devolve = devolve
        self.recebeu = None

    def predict(self, atributos):
        self.recebeu = atributos
        return [self.devolve]


class ModeloQuebrado:
    def predict(self, atributos):
        raise RuntimeError("modelo de outra versão do scikit-learn")


@pytest.fixture
def modelos(monkeypatch):
    """Instala modelos em memória, como o create_app faria."""

    def instalar(**por_arquivo):
        monkeypatch.setattr(previsao_service, "_modelos", dict(por_arquivo))
        return por_arquivo

    return instalar


def medidor_de(arquivo_modelo="modelo_consumo_producao.pkl", limite=None):
    medidor = Medidor(id=1, codigo="MED-PROD", id_setor=1, ativo=True)
    medidor.setor = Setor(
        id=1, nome="Produção", ativo=True,
        arquivo_modelo=arquivo_modelo, limite_consumo_kwh=limite,
    )
    return medidor


def leituras(*consumos):
    """Leituras da mais nova para a mais antiga, como o repositório devolve."""
    return [Leitura(id_medidor=1, consumo_kwh=Decimal(str(c))) for c in consumos]


QUATRO = leituras("20.0", "19.5", "19.0", "18.5")
# Quarta-feira, 3 de janeiro de 2018, 12:30.
INSTANTE = datetime(2018, 1, 3, 12, 30)


# ---------------------------------------------------------------------------
# Os atributos
# ---------------------------------------------------------------------------


def test_atributos_tem_os_9_nomes_na_ordem_do_notebook():
    """O contrato com notebooks/preparacao.py: mesmos nomes, mesma ordem."""
    linha = previsao_service.montar_atributos(INSTANTE, QUATRO)
    assert list(linha.columns) == [
        "hora", "minuto", "dia_semana", "mes", "fim_de_semana",
        "lag_1", "lag_2", "lag_3", "lag_4",
    ]
    assert len(linha) == 1


def test_calendario_vem_do_periodo_a_prever():
    linha = previsao_service.montar_atributos(INSTANTE, QUATRO).iloc[0]
    assert linha.hora == 12
    assert linha.minuto == 30
    assert linha.dia_semana == 2  # quarta-feira
    assert linha.mes == 1
    assert linha.fim_de_semana == 0


@pytest.mark.parametrize("dia, fim_de_semana", [(5, 0), (6, 1), (7, 1), (8, 0)])
def test_fim_de_semana_marca_sabado_e_domingo(dia, fim_de_semana):
    """6 e 7 de janeiro de 2018 são sábado e domingo."""
    quando = datetime(2018, 1, dia, 10, 0)
    assert previsao_service.montar_atributos(quando, QUATRO).iloc[0].fim_de_semana == fim_de_semana


def test_lag_1_e_a_leitura_mais_recente():
    """O repositório devolve da mais nova para a mais antiga; lag_1 é a primeira."""
    linha = previsao_service.montar_atributos(INSTANTE, QUATRO).iloc[0]
    assert (linha.lag_1, linha.lag_2, linha.lag_3, linha.lag_4) == (20.0, 19.5, 19.0, 18.5)


def test_leituras_a_mais_sao_ignoradas():
    """Cinco leituras não viram lag_5: o modelo foi treinado com quatro."""
    linha = previsao_service.montar_atributos(INSTANTE, leituras(1, 2, 3, 4, 5)).iloc[0]
    assert linha.lag_4 == 4.0


# ---------------------------------------------------------------------------
# Quando NÃO dá para prever — regras 4 e 9, e nenhum deles é erro
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("quantidade", [0, 1, 2, 3])
def test_menos_de_4_leituras_devolve_none(modelos, quantidade):
    """Regra 4, caso de borda obrigatório."""
    modelos(**{"modelo_consumo_producao.pkl": ModeloFalso()})
    anteriores = leituras(*range(quantidade))
    assert previsao_service.prever(medidor_de(), INSTANTE, anteriores) is None


def test_com_exatamente_4_leituras_preve(modelos):
    modelos(**{"modelo_consumo_producao.pkl": ModeloFalso(42.0)})
    assert previsao_service.prever(medidor_de(), INSTANTE, QUATRO) == Decimal("42.000")


def test_setor_sem_arquivo_modelo_devolve_none(modelos):
    """Regra 9: setor sem modelo não é erro, é 'sem previsão ainda'."""
    modelos(**{"modelo_consumo_producao.pkl": ModeloFalso()})
    assert previsao_service.prever(medidor_de(arquivo_modelo=None), INSTANTE, QUATRO) is None


def test_arquivo_ausente_devolve_none(modelos):
    """Regra 9: o setor aponta para um .pkl que não está carregado."""
    modelos()  # nenhum modelo em memória
    assert previsao_service.prever(medidor_de(), INSTANTE, QUATRO) is None


def test_medidor_sem_setor_devolve_none(modelos):
    modelos(**{"modelo_consumo_producao.pkl": ModeloFalso()})
    medidor = Medidor(id=1, codigo="MED-X", id_setor=1, ativo=True)
    medidor.setor = None
    assert previsao_service.prever(medidor, INSTANTE, QUATRO) is None


def test_modelo_que_levanta_excecao_devolve_none_e_nao_derruba(modelos):
    """Um .pkl de outra versão do scikit-learn não pode derrubar a leitura."""
    modelos(**{"modelo_consumo_producao.pkl": ModeloQuebrado()})
    assert previsao_service.prever(medidor_de(), INSTANTE, QUATRO) is None


# ---------------------------------------------------------------------------
# Regra 5 e regra 9
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("devolvido", [-0.001, -5.0, -1000.0])
def test_previsao_nunca_e_negativa(modelos, devolvido):
    """Regra 5: a regressão pode extrapolar para baixo; o serviço trunca em 0."""
    modelos(**{"modelo_consumo_producao.pkl": ModeloFalso(devolvido)})
    assert previsao_service.prever(medidor_de(), INSTANTE, QUATRO) == Decimal("0.000")


def test_previsao_tem_3_casas_como_a_coluna(modelos):
    """consumo_previsto_kwh é DECIMAL(10,3)."""
    modelos(**{"modelo_consumo_producao.pkl": ModeloFalso(12.3456789)})
    assert previsao_service.prever(medidor_de(), INSTANTE, QUATRO) == Decimal("12.346")


def test_cada_setor_usa_o_seu_modelo(modelos):
    """Regra 9, critério da #26: mesmas leituras, setores diferentes, previsões diferentes."""
    modelos(**{
        "modelo_consumo_producao.pkl": ModeloFalso(100.0),
        "modelo_consumo_utilidades.pkl": ModeloFalso(7.0),
    })
    producao = previsao_service.prever(medidor_de("modelo_consumo_producao.pkl"), INSTANTE, QUATRO)
    utilidades = previsao_service.prever(
        medidor_de("modelo_consumo_utilidades.pkl"), INSTANTE, QUATRO
    )
    assert (producao, utilidades) == (Decimal("100.000"), Decimal("7.000"))


# ---------------------------------------------------------------------------
# O carregamento — regra 9
# ---------------------------------------------------------------------------


def test_pasta_inexistente_nao_derruba_a_aplicacao(tmp_path):
    relatorio = previsao_service.carregar_modelos(tmp_path / "nao-existe")
    assert relatorio["carregados"] == []
    assert previsao_service.modelos_carregados() == []


def test_pkl_corrompido_fica_de_fora_sem_derrubar(tmp_path):
    """O modelo quebrado sai do dicionário; os outros continuam valendo."""
    import joblib

    joblib.dump(ModeloFalso(1.0), tmp_path / "modelo_consumo_bom.pkl")
    (tmp_path / "modelo_consumo_ruim.pkl").write_bytes(b"isto nao e um pickle")

    relatorio = previsao_service.carregar_modelos(tmp_path)

    assert relatorio["carregados"] == ["modelo_consumo_bom.pkl"]
    assert "modelo_consumo_ruim.pkl" in relatorio["falharam"]
    assert previsao_service.modelos_carregados() == ["modelo_consumo_bom.pkl"]


def test_carregar_duas_vezes_nao_acumula(tmp_path):
    """Carregar de novo substitui, não soma — senão um modelo removido sobreviveria."""
    import joblib

    joblib.dump(ModeloFalso(), tmp_path / "modelo_consumo_producao.pkl")
    previsao_service.carregar_modelos(tmp_path)
    previsao_service.carregar_modelos(tmp_path / "vazia")
    assert previsao_service.modelos_carregados() == []
