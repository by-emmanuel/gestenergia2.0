"""Testes dos models sem banco (issue #8).

Conferem o que da para conferir so com o metadata do SQLAlchemy: nomes de
tabela, de coluna e de restricao, e as acoes das chaves estrangeiras. Os nomes
vem do banco.sql e precisam bater exatamente — e o banco.sql que vai para o
professor em 23/11.

A comparacao contra o schema real do MySQL esta em tests/integration/test_models.py.
"""

import pytest

from app.banco import Base
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

TABELAS_DO_BANCO_SQL = {
    "usuarios_sistema",
    "setores",
    "medidores",
    "leituras_energia",
    "alertas",
}

COLUNAS_DO_BANCO_SQL = {
    "usuarios_sistema": {"id", "nome", "email", "senha_hash", "perfil", "ativo", "criado_em"},
    "setores": {
        "id", "nome", "descricao", "limite_consumo_kwh", "arquivo_modelo",
        "tem_fator_potencia", "ativo", "criado_em",
    },
    "medidores": {"id", "id_setor", "codigo", "descricao", "ativo", "criado_em"},
    "leituras_energia": {
        "id", "id_medidor", "data_hora", "consumo_kwh", "fator_potencia",
        "consumo_previsto_kwh", "reativa_atrasada_kvarh", "reativa_adiantada_kvarh",
        "co2_t", "criado_em",
    },
    "alertas": {
        "id", "id_leitura", "tipo", "valor_observado", "limite_referencia", "mensagem",
        "status", "criado_em", "resolvido_em", "id_usuario_resolucao",
        # Issue #28: o que o gestor escreveu ao resolver.
        "observacao_resolucao",
    },
}


def test_os_5_models_cobrem_as_5_tabelas():
    assert set(Base.metadata.tables) == TABELAS_DO_BANCO_SQL


@pytest.mark.parametrize("tabela", sorted(TABELAS_DO_BANCO_SQL))
def test_colunas_batem_com_o_banco_sql(tabela):
    colunas = {coluna.name for coluna in Base.metadata.tables[tabela].columns}

    assert colunas == COLUNAS_DO_BANCO_SQL[tabela]


def test_o_nome_da_tabela_de_cada_model():
    assert Usuario.__tablename__ == "usuarios_sistema"
    assert Setor.__tablename__ == "setores"
    assert Medidor.__tablename__ == "medidores"
    assert Leitura.__tablename__ == "leituras_energia"
    assert Alerta.__tablename__ == "alertas"


def _nomes_de_restricao(tabela: str) -> set[str]:
    return {
        restricao.name
        for restricao in Base.metadata.tables[tabela].constraints
        if restricao.name
    }


def test_restricoes_que_defendem_as_regras_de_negocio():
    """Os nomes sao os mesmos do banco.sql, para os dois schemas conferirem."""
    # Regra 3: leitura duplicada proibida. Regras 5 e 6.
    assert "uq_leitura_medidor_data_hora" in _nomes_de_restricao("leituras_energia")
    assert "ck_leitura_previsto_nao_negativo" in _nomes_de_restricao("leituras_energia")
    assert "ck_leitura_fator_entre_0_e_1" in _nomes_de_restricao("leituras_energia")
    assert "ck_leitura_consumo_nao_negativo" in _nomes_de_restricao("leituras_energia")
    # Regra 10: limite coerente.
    assert "ck_setor_limite_positivo" in _nomes_de_restricao("setores")
    # Auditoria do alerta.
    assert "ck_alerta_resolucao_coerente" in _nomes_de_restricao("alertas")
    assert "uq_alerta_leitura_tipo" in _nomes_de_restricao("alertas")
    # Chaves naturais.
    assert "uq_usuario_email" in _nomes_de_restricao("usuarios_sistema")
    assert "uq_setor_nome" in _nomes_de_restricao("setores")
    assert "uq_medidor_codigo" in _nomes_de_restricao("medidores")


def _chave_estrangeira(tabela: str, nome: str):
    for restricao in Base.metadata.tables[tabela].foreign_key_constraints:
        if restricao.name == nome:
            return restricao
    raise AssertionError(f"chave estrangeira {nome} nao existe em {tabela}")


def test_acoes_das_chaves_estrangeiras_batem_com_o_banco_sql():
    # Apagar setor com medidor e proibido.
    assert _chave_estrangeira("medidores", "fk_medidor_setor").ondelete == "RESTRICT"
    # Apagar medidor leva junto as leituras, e leitura leva junto os alertas.
    assert _chave_estrangeira("leituras_energia", "fk_leitura_medidor").ondelete == "CASCADE"
    assert _chave_estrangeira("alertas", "fk_alerta_leitura").ondelete == "CASCADE"


def test_fk_alerta_usuario_e_restrict_e_nao_set_null():
    """Decisao de 08/10: o MySQL 8 recusa acao referencial em coluna de CHECK.

    id_usuario_resolucao participa de ck_alerta_resolucao_coerente, entao a acao
    tem de ser RESTRICT (erro 3823). Voltar para SET NULL quebra o banco.sql.
    """
    fk = _chave_estrangeira("alertas", "fk_alerta_usuario")

    assert fk.ondelete == "RESTRICT"
    assert fk.onupdate == "RESTRICT"


def test_valores_dos_enums_batem_com_o_banco_sql():
    assert [p.value for p in PerfilUsuario] == ["OPERADOR", "GESTOR"]
    assert [t.value for t in TipoAlerta] == ["CONSUMO_ACIMA_LIMITE", "FATOR_POTENCIA_BAIXO"]
    assert [s.value for s in StatusAlerta] == ["ABERTO", "RESOLVIDO"]


def test_colunas_que_aceitam_nulo():
    """Regra 1: fator NULL e normal. Regra 4: previsao NULL com menos de 4 leituras."""
    leituras = Base.metadata.tables["leituras_energia"]

    assert leituras.columns["fator_potencia"].nullable is True
    assert leituras.columns["consumo_previsto_kwh"].nullable is True
    assert leituras.columns["consumo_kwh"].nullable is False
    assert leituras.columns["data_hora"].nullable is False


def test_limite_e_arquivo_do_modelo_aceitam_nulo():
    """Regra 9: setor sem modelo devolve None. O limite fica NULL ate a #44."""
    setores = Base.metadata.tables["setores"]

    assert setores.columns["limite_consumo_kwh"].nullable is True
    assert setores.columns["arquivo_modelo"].nullable is True


def test_e_gestor_distingue_os_dois_perfis():
    gestor = Usuario(nome="G", email="g@x", senha_hash="h", perfil=PerfilUsuario.GESTOR)
    operador = Usuario(nome="O", email="o@x", senha_hash="h", perfil=PerfilUsuario.OPERADOR)

    assert gestor.e_gestor is True
    assert operador.e_gestor is False
