"""Models do SQLAlchemy (issue #8).

Espelham o banco.sql tabela por tabela, coluna por coluna, com os MESMOS nomes
de restricao. Isso e proposital: o banco.sql e a fonte do schema (e o arquivo
entregue ao professor em 23/11), e os models tem de poder recriar o mesmo schema
nos testes. O teste tests/integration/test_models.py compara os dois e falha se
divergirem.

As regras de negocio NAO moram aqui, e sim nos services. O que esta aqui sao as
restricoes de integridade, que o banco impoe mesmo se o codigo tiver bug:

    regra 3  uq_leitura_medidor_data_hora     leitura duplicada proibida
    regra 5  ck_leitura_previsto_nao_negativo previsao nunca negativa
    regra 6  ck_leitura_fator_entre_0_e_1     fator guardado de 0 a 1
    regra 10 ck_setor_limite_positivo         limite coerente
"""

import enum
from datetime import datetime
from decimal import Decimal

from flask_login import UserMixin
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .banco import Base


class PerfilUsuario(str, enum.Enum):
    """Regra 7: OPERADOR registra e importa leituras; GESTOR faz tudo."""

    OPERADOR = "OPERADOR"
    GESTOR = "GESTOR"


class TipoAlerta(str, enum.Enum):
    """Os dois tipos de alerta do sistema (regras 1 e 2)."""

    CONSUMO_ACIMA_LIMITE = "CONSUMO_ACIMA_LIMITE"
    FATOR_POTENCIA_BAIXO = "FATOR_POTENCIA_BAIXO"


class StatusAlerta(str, enum.Enum):
    """Alerta nasce ABERTO e o GESTOR o passa para RESOLVIDO (issue #28)."""

    ABERTO = "ABERTO"
    RESOLVIDO = "RESOLVIDO"


class Usuario(UserMixin, Base):
    """Usuario do sistema. A senha vai SEMPRE em hash, nunca em texto.

    O UserMixin vem do Flask-Login (issue #10) e da de graca o get_id() e as
    propriedades de sessao. O is_active e sobrescrito abaixo: o padrao do mixin
    devolve True sempre, e aqui quem manda e a coluna ativo.
    """

    __tablename__ = "usuarios_sistema"
    __table_args__ = (UniqueConstraint("email", name="uq_usuario_email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(180), nullable=False)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    perfil: Mapped[PerfilUsuario] = mapped_column(
        Enum(PerfilUsuario, name="perfil_usuario"), nullable=False
    )
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    criado_em: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    alertas_resolvidos: Mapped[list["Alerta"]] = relationship(
        back_populates="usuario_resolucao"
    )

    @property
    def e_gestor(self) -> bool:
        """Atalho de leitura para as telas e os decoradores de perfil (#10)."""
        return self.perfil is PerfilUsuario.GESTOR

    @property
    def is_active(self) -> bool:
        """Flask-Login: usuario desativado nao consegue abrir sessao."""
        return bool(self.ativo)

    def __repr__(self) -> str:
        return f"<Usuario {self.email} ({self.perfil.value})>"


class Setor(Base):
    """Setor da industria. Cada um tem o seu limite e o seu modelo (regra 9)."""

    __tablename__ = "setores"
    __table_args__ = (
        UniqueConstraint("nome", name="uq_setor_nome"),
        CheckConstraint(
            "limite_consumo_kwh IS NULL OR limite_consumo_kwh > 0",
            name="ck_setor_limite_positivo",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    descricao: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # NULL ate a issue #44 calcular o percentil 99. Enquanto for NULL, o setor
    # nao gera alerta de consumo acima do limite.
    limite_consumo_kwh: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    # Regra 9: o .pkl daquele setor, dentro de ml/. NULL ou ausente -> previsao None.
    arquivo_modelo: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Hoje so a Producao tem fator de potencia (regra 1).
    tem_fator_potencia: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    criado_em: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    medidores: Mapped[list["Medidor"]] = relationship(back_populates="setor")

    def __repr__(self) -> str:
        return f"<Setor {self.nome}>"


class Medidor(Base):
    """Medidor de um setor. O setor do medidor define o modelo e o limite."""

    __tablename__ = "medidores"
    __table_args__ = (
        UniqueConstraint("codigo", name="uq_medidor_codigo"),
        Index("ix_medidor_setor", "id_setor"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id_setor: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "setores.id",
            name="fk_medidor_setor",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        nullable=False,
    )
    codigo: Mapped[str] = mapped_column(String(60), nullable=False)
    descricao: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    criado_em: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    setor: Mapped["Setor"] = relationship(back_populates="medidores")
    leituras: Mapped[list["Leitura"]] = relationship(
        back_populates="medidor", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Medidor {self.codigo}>"


class Leitura(Base):
    """Leitura de consumo de um medidor, a cada 15 minutos.

    As colunas reativa_* e co2_t existem porque a base da siderurgica tem esses
    dados, mas NUNCA entram como atributo do modelo: sao do mesmo periodo do
    alvo e vazariam a resposta.
    """

    __tablename__ = "leituras_energia"
    __table_args__ = (
        # Regra 3: um medidor nao pode ter duas leituras na mesma data_hora.
        UniqueConstraint("id_medidor", "data_hora", name="uq_leitura_medidor_data_hora"),
        Index("ix_leitura_data_hora", "data_hora"),
        CheckConstraint("consumo_kwh >= 0", name="ck_leitura_consumo_nao_negativo"),
        # Regra 5: previsao nunca negativa.
        CheckConstraint(
            "consumo_previsto_kwh IS NULL OR consumo_previsto_kwh >= 0",
            name="ck_leitura_previsto_nao_negativo",
        ),
        # Regra 6: fator guardado de 0 a 1, nunca em percentual.
        CheckConstraint(
            "fator_potencia IS NULL OR (fator_potencia >= 0 AND fator_potencia <= 1)",
            name="ck_leitura_fator_entre_0_e_1",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_medidor: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "medidores.id",
            name="fk_leitura_medidor",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=False,
    )
    data_hora: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumo_kwh: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    # Regra 1: NULL quando o setor nao tem o dado. Nao gera alerta e nao da erro.
    fator_potencia: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    # Regra 4: NULL quando o medidor tem menos de 4 leituras anteriores.
    consumo_previsto_kwh: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    reativa_atrasada_kvarh: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    reativa_adiantada_kvarh: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    co2_t: Mapped[Decimal | None] = mapped_column(Numeric(10, 5), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    medidor: Mapped["Medidor"] = relationship(back_populates="leituras")
    alertas: Mapped[list["Alerta"]] = relationship(
        back_populates="leitura", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Leitura medidor={self.id_medidor} {self.data_hora}>"


class Alerta(Base):
    """Alerta aberto por uma leitura.

    valor_observado e limite_referencia ficam guardados para auditoria: permitem
    reconstruir depois por que o alerta foi aberto, mesmo que o limite do setor
    mude.
    """

    __tablename__ = "alertas"
    __table_args__ = (
        UniqueConstraint("id_leitura", "tipo", name="uq_alerta_leitura_tipo"),
        Index("ix_alerta_status", "status"),
        CheckConstraint(
            "(status = 'ABERTO'    AND resolvido_em IS NULL     AND id_usuario_resolucao IS NULL"
            "                      AND observacao_resolucao IS NULL)"
            " OR "
            "(status = 'RESOLVIDO' AND resolvido_em IS NOT NULL AND id_usuario_resolucao IS NOT NULL"
            "                      AND observacao_resolucao IS NOT NULL)",
            name="ck_alerta_resolucao_coerente",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_leitura: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "leituras_energia.id",
            name="fk_alerta_leitura",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=False,
    )
    tipo: Mapped[TipoAlerta] = mapped_column(Enum(TipoAlerta, name="tipo_alerta"), nullable=False)
    valor_observado: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    limite_referencia: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    mensagem: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[StatusAlerta] = mapped_column(
        Enum(StatusAlerta, name="status_alerta"),
        nullable=False,
        server_default=StatusAlerta.ABERTO.value,
    )
    criado_em: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    resolvido_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # RESTRICT nas duas acoes por imposicao do MySQL 8: coluna usada em CHECK nao
    # aceita acao referencial (erro 3823). Ver a decisao de 08/10 no progress.json.
    id_usuario_resolucao: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "usuarios_sistema.id",
            name="fk_alerta_usuario",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=True,
    )

    # Issue #28: o que o gestor escreveu ao resolver. Obrigatoria na resolucao
    # pelo CHECK acima — alerta resolvido sem explicacao nao serve a auditoria.
    observacao_resolucao: Mapped[str | None] = mapped_column(String(500), nullable=True)

    leitura: Mapped["Leitura"] = relationship(back_populates="alertas")
    usuario_resolucao: Mapped["Usuario | None"] = relationship(
        back_populates="alertas_resolvidos"
    )

    def __repr__(self) -> str:
        return f"<Alerta {self.tipo.value} {self.status.value}>"
