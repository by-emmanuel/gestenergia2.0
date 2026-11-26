"""Testes dos models contra um MySQL de verdade (issue #8).

Exige o banco de pe:  docker compose up -d db

Dois grupos:

1. O espelho. Compara o schema que os models criam no gestenergia_test com o
   schema que o banco.sql criou no gestenergia. Se alguem mexer num sem mexer no
   outro, este teste aponta exatamente a diferenca. E a garantia de que os
   testes de integracao rodam contra o mesmo banco do sistema.

2. As restricoes. Conferem que o banco recusa o dado errado mesmo quando o
   codigo manda errado — as regras 3, 5, 6 e a coerencia do alerta resolvido.
"""

import re
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import DatabaseError, IntegrityError

from app.config import Config
from app.models import (
    Alerta,
    Leitura,
    Medidor,
    PerfilUsuario,
    Setor,
    StatusAlerta,
    TipoAlerta,
    Usuario,
)

TABELAS = ["alertas", "leituras_energia", "medidores", "setores", "usuarios_sistema"]


# ---------------------------------------------------------------------------
# 1. Os models espelham o banco.sql
# ---------------------------------------------------------------------------


def _normalizar_check(sqltext: str) -> str:
    """Tira o prefixo de charset dos literais, que e cosmetico.

    O MySQL guarda a expressao do CHECK ja normalizada, mas prefixa os literais
    com o charset da conexao que criou a tabela: o banco.sql sai com
    _latin1'ABERTO' e o SQLAlchemy com _utf8mb4'ABERTO'. A regra e a mesma.
    """
    return re.sub(r"_[a-z0-9]+'", "'", sqltext).strip()


def _retrato_do_schema(motor: Engine, nome_do_banco: str) -> dict:
    """Le o schema do MySQL e devolve um dicionario comparavel."""
    inspetor = inspect(motor)
    retrato = {}
    for tabela in TABELAS:
        colunas = {
            coluna["name"]: (str(coluna["type"]), bool(coluna["nullable"]))
            for coluna in inspetor.get_columns(tabela, schema=nome_do_banco)
        }
        unicas = {
            restricao["name"]: sorted(restricao["column_names"])
            for restricao in inspetor.get_unique_constraints(tabela, schema=nome_do_banco)
        }
        estrangeiras = {
            restricao["name"]: (
                sorted(restricao["constrained_columns"]),
                restricao["referred_table"],
                restricao.get("options", {}).get("ondelete"),
            )
            for restricao in inspetor.get_foreign_keys(tabela, schema=nome_do_banco)
        }
        # Os CHECK sao o que defende as regras de negocio dentro do banco.
        verificacoes = {
            restricao["name"]: _normalizar_check(restricao["sqltext"])
            for restricao in inspetor.get_check_constraints(tabela, schema=nome_do_banco)
        }
        retrato[tabela] = {
            "colunas": colunas,
            "unicas": unicas,
            "estrangeiras": estrangeiras,
            "verificacoes": verificacoes,
        }
    return retrato


@pytest.fixture
def schema_do_banco_sql():
    """Schema real do gestenergia, criado pelo banco.sql."""
    motor_producao = create_engine(
        Config.SQLALCHEMY_DATABASE_URI,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3},
    )
    try:
        with motor_producao.connect() as conexao:
            existentes = conexao.execute(text("SHOW TABLES")).scalars().all()
        if sorted(existentes) != TABELAS:
            pytest.skip(
                "banco gestenergia sem as 5 tabelas: rode 'docker compose down -v && "
                "docker compose up -d db' para reaplicar o banco.sql"
            )
        yield _retrato_do_schema(motor_producao, Config.NOME_DO_BANCO)
    except Exception as erro:
        pytest.skip(f"banco gestenergia indisponivel ({type(erro).__name__})")
    finally:
        motor_producao.dispose()


def test_models_criam_as_5_tabelas(banco):
    assert sorted(inspect(banco).get_table_names()) == TABELAS


@pytest.mark.parametrize("tabela", TABELAS)
def test_models_espelham_o_banco_sql(banco, schema_do_banco_sql, app, tabela):
    """O schema dos models tem de ser igual ao que o banco.sql cria.

    Divergiu? Ou o banco.sql mudou sem os models, ou o contrario. Os dois
    precisam andar juntos: o banco.sql e a entrega de 23/11 e os models sao o
    que o sistema usa.
    """
    dos_models = _retrato_do_schema(banco, app.config["NOME_DO_BANCO"])[tabela]
    do_sql = schema_do_banco_sql[tabela]

    assert dos_models["colunas"] == do_sql["colunas"]
    assert dos_models["unicas"] == do_sql["unicas"]
    assert dos_models["estrangeiras"] == do_sql["estrangeiras"]
    assert dos_models["verificacoes"] == do_sql["verificacoes"]


# ---------------------------------------------------------------------------
# 2. As restricoes defendem as regras de negocio
# ---------------------------------------------------------------------------


@pytest.fixture
def setor_com_medidor(sessao):
    """Um setor de Producao com um medidor, que e o minimo para ter leitura."""
    setor = Setor(
        nome="Producao",
        descricao="Setor de teste",
        limite_consumo_kwh=Decimal("100.000"),
        arquivo_modelo="modelo_consumo_producao.pkl",
        tem_fator_potencia=True,
    )
    medidor = Medidor(setor=setor, codigo="MED-TESTE", descricao="Medidor de teste")
    sessao.add(medidor)
    sessao.commit()
    return medidor


def test_relacionamentos_navegam_nos_dois_sentidos(sessao, setor_com_medidor):
    medidor = setor_com_medidor
    leitura = Leitura(
        medidor=medidor,
        data_hora=datetime(2018, 1, 1, 0, 0),
        consumo_kwh=Decimal("120.000"),
        fator_potencia=Decimal("0.950"),
    )
    sessao.add(leitura)
    sessao.commit()

    assert leitura.medidor.codigo == "MED-TESTE"
    assert leitura.medidor.setor.nome == "Producao"
    assert medidor.setor.medidores == [medidor]
    assert medidor.leituras == [leitura]


def test_leitura_duplicada_e_recusada_pelo_banco(sessao, setor_com_medidor):
    """Regra 3: um medidor nao pode ter duas leituras na mesma data_hora."""
    quando = datetime(2018, 1, 1, 0, 15)
    sessao.add(Leitura(medidor=setor_com_medidor, data_hora=quando, consumo_kwh=Decimal("10")))
    sessao.commit()

    sessao.add(Leitura(medidor=setor_com_medidor, data_hora=quando, consumo_kwh=Decimal("99")))

    with pytest.raises(IntegrityError):
        sessao.commit()


def test_previsao_negativa_e_recusada_pelo_banco(sessao, setor_com_medidor):
    """Regra 5: a previsao nunca e negativa."""
    sessao.add(
        Leitura(
            medidor=setor_com_medidor,
            data_hora=datetime(2018, 1, 1, 0, 30),
            consumo_kwh=Decimal("10"),
            consumo_previsto_kwh=Decimal("-0.500"),
        )
    )

    with pytest.raises(DatabaseError):
        sessao.commit()


def test_fator_de_potencia_acima_de_1_e_recusado(sessao, setor_com_medidor):
    """Regra 6: o fator e guardado de 0 a 1, nunca em percentual."""
    sessao.add(
        Leitura(
            medidor=setor_com_medidor,
            data_hora=datetime(2018, 1, 1, 0, 45),
            consumo_kwh=Decimal("10"),
            fator_potencia=Decimal("1.500"),
        )
    )

    with pytest.raises(DatabaseError):
        sessao.commit()


def test_limite_do_setor_igual_a_zero_e_recusado(sessao):
    """Regra 10: limite NULL e permitido (ate a #44); zero nao."""
    sessao.add(Setor(nome="Setor zerado", limite_consumo_kwh=Decimal("0")))

    with pytest.raises(DatabaseError):
        sessao.commit()


def test_setor_sem_limite_e_sem_modelo_e_aceito(sessao):
    """E o estado dos 4 setores hoje: limite e modelo so chegam na #44 e na #25."""
    sessao.add(Setor(nome="Administrativo"))
    sessao.commit()

    setor = sessao.query(Setor).filter_by(nome="Administrativo").one()
    assert setor.limite_consumo_kwh is None
    assert setor.arquivo_modelo is None
    assert setor.tem_fator_potencia is False


def test_alerta_aberto_nasce_sem_quem_resolveu(sessao, setor_com_medidor):
    leitura = Leitura(
        medidor=setor_com_medidor,
        data_hora=datetime(2018, 1, 1, 1, 0),
        consumo_kwh=Decimal("150"),
        consumo_previsto_kwh=Decimal("150"),
    )
    alerta = Alerta(
        leitura=leitura,
        tipo=TipoAlerta.CONSUMO_ACIMA_LIMITE,
        valor_observado=Decimal("150"),
        limite_referencia=Decimal("100"),
        mensagem="Consumo previsto acima do limite do setor",
    )
    sessao.add(alerta)
    sessao.commit()

    assert alerta.status is StatusAlerta.ABERTO
    assert alerta.resolvido_em is None
    assert alerta.usuario_resolucao is None
    assert alerta.leitura.medidor.setor.nome == "Producao"


def test_alerta_resolvido_sem_quem_resolveu_e_recusado(sessao, setor_com_medidor):
    """O alerta RESOLVIDO tem de dizer quem resolveu e quando."""
    leitura = Leitura(
        medidor=setor_com_medidor,
        data_hora=datetime(2018, 1, 1, 1, 15),
        consumo_kwh=Decimal("150"),
    )
    sessao.add(
        Alerta(
            leitura=leitura,
            tipo=TipoAlerta.CONSUMO_ACIMA_LIMITE,
            valor_observado=Decimal("150"),
            limite_referencia=Decimal("100"),
            status=StatusAlerta.RESOLVIDO,
            resolvido_em=datetime(2018, 1, 1, 2, 0),
        )
    )

    with pytest.raises(DatabaseError):
        sessao.commit()


def test_alerta_resolvido_por_um_gestor_e_aceito(sessao, setor_com_medidor):
    gestor = Usuario(
        nome="Gestor de Energia",
        email="gestor@teste.local",
        senha_hash="pbkdf2:sha256:600000$fake",
        perfil=PerfilUsuario.GESTOR,
    )
    leitura = Leitura(
        medidor=setor_com_medidor,
        data_hora=datetime(2018, 1, 1, 1, 30),
        consumo_kwh=Decimal("150"),
    )
    alerta = Alerta(
        leitura=leitura,
        tipo=TipoAlerta.FATOR_POTENCIA_BAIXO,
        valor_observado=Decimal("0.800"),
        limite_referencia=Decimal("0.920"),
        status=StatusAlerta.RESOLVIDO,
        resolvido_em=datetime(2018, 1, 1, 2, 0),
        usuario_resolucao=gestor,
        # Issue #28: o CHECK exige a observacao quando o alerta e RESOLVIDO.
        observacao_resolucao="Banco de capacitores religado",
    )
    sessao.add(alerta)
    sessao.commit()

    assert alerta.usuario_resolucao.e_gestor is True
    assert gestor.alertas_resolvidos == [alerta]


def test_dois_alertas_do_mesmo_tipo_na_mesma_leitura_sao_recusados(sessao, setor_com_medidor):
    leitura = Leitura(
        medidor=setor_com_medidor,
        data_hora=datetime(2018, 1, 1, 1, 45),
        consumo_kwh=Decimal("150"),
    )
    sessao.add(
        Alerta(
            leitura=leitura,
            tipo=TipoAlerta.FATOR_POTENCIA_BAIXO,
            valor_observado=Decimal("0.800"),
            limite_referencia=Decimal("0.920"),
        )
    )
    sessao.commit()

    sessao.add(
        Alerta(
            leitura=leitura,
            tipo=TipoAlerta.FATOR_POTENCIA_BAIXO,
            valor_observado=Decimal("0.700"),
            limite_referencia=Decimal("0.920"),
        )
    )

    with pytest.raises(IntegrityError):
        sessao.commit()


def test_email_de_usuario_e_unico(sessao):
    for _ in range(2):
        sessao.add(
            Usuario(
                nome="Alguem",
                email="repetido@teste.local",
                senha_hash="h",
                perfil=PerfilUsuario.OPERADOR,
            )
        )

    with pytest.raises(IntegrityError):
        sessao.commit()
