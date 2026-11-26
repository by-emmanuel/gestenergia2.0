"""Abertura de alertas a cada leitura (issue #27, regras 1 e 2).

Os dois alertas do sistema, e a assimetria entre eles:

  - **CONSUMO_ACIMA_LIMITE** (regra 2) olha o consumo PREVISTO, nao o medido. E
    o ponto do sistema: avisar antes de acontecer. Sem previsao nao ha alerta de
    consumo — nao e falha, e o que a regra 4 descreve.
  - **FATOR_POTENCIA_BAIXO** (regra 1) olha o valor MEDIDO, porque fator de
    potencia nao e previsto por nenhum modelo deste projeto. So o setor Producao
    tem esse dado; nos outros a leitura vem com NULL, nao gera alerta e NAO DA
    ERRO.

Nos dois casos a comparacao e estrita: exatamente 0,92 nao gera alerta, e
consumo exatamente igual ao limite nao gera alerta. Esta escrito assim no
CLAUDE.md e ha teste de borda para 0,91 / 0,92 / 0,93.

Quanto alerta isso produz, medido na issue #44: o de consumo da entre 5,2 e 7,5
por semana por setor (percentil 99, regra 10). O de fator de potencia da ~406
por semana so na Producao, porque 60,4% dos periodos da siderurgica estao abaixo
de 0,92. A regra ficou como esta por decisao de 10/10 — e e por isso que a tela
de resolver alertas (#28) TEM de filtrar por tipo e por status e paginar.
"""

from datetime import datetime
from decimal import Decimal

from ..models import Alerta, Leitura, StatusAlerta, TipoAlerta
from ..repositories import alerta_repository

# Issue #28: quantos alertas por pagina. 25 cabe numa tela sem rolar demais e
# mantem a consulta barata mesmo com milhares de linhas.
POR_PAGINA = 25
TAMANHO_DA_OBSERVACAO = 500
OBSERVACAO_MINIMA = 3

# Regra 1: minimo da ANEEL. Decimal, NUNCA float: a coluna e DECIMAL(4,3), e
# comparar Decimal("0.920") com o float 0.92 da True, porque 0.92 em binario e
# 0.92000000000000004. Era esse o defeito que marcava exatamente 0,92 como
# violacao, e o CLAUDE.md e explicito: 0,92 NAO gera alerta.
FATOR_POTENCIA_MINIMO = Decimal("0.92")

MENSAGEM_CONSUMO = (
    "Consumo previsto de {previsto} kWh para {quando}, acima do limite de {limite} kWh do setor {setor}."
)
MENSAGEM_FATOR = (
    "Fator de potência de {fator} medido em {quando}, abaixo do mínimo de 0,92 exigido pela ANEEL."
)


def fator_abaixo_do_minimo(leitura: Leitura) -> bool:
    """Regra 1: o fator esta abaixo de 0,92?

    Exatamente 0,92 devolve False — nao e violacao. Leitura sem o dado tambem
    devolve False, sem erro: hoje so o setor Producao tem fator de potencia.
    """
    if leitura.fator_potencia is None:
        return False
    return leitura.fator_potencia < FATOR_POTENCIA_MINIMO


def consumo_acima_do_limite(previsto: Decimal | None, limite: Decimal | None) -> bool:
    """Regra 2: o consumo PREVISTO passou do limite daquele setor?

    Devolve False quando falta a previsao (regra 4: menos de 4 leituras, ou setor
    sem modelo) ou quando o setor ainda nao tem limite. Nos dois casos nao ha com
    o que comparar — nao e violacao e nao e erro.
    """
    if previsto is None or limite is None:
        return False
    return previsto > limite


def avaliar(leitura: Leitura) -> list[Alerta]:
    """Monta os alertas que esta leitura abre. NAO grava nada.

    Separado de `abrir_para` de proposito: assim a regra inteira se testa sem
    banco nenhum, que e o que `tests/unit` cobra.
    """
    setor = leitura.medidor.setor if leitura.medidor is not None else None
    alertas = []

    limite = setor.limite_consumo_kwh if setor is not None else None
    if consumo_acima_do_limite(leitura.consumo_previsto_kwh, limite):
        alertas.append(
            Alerta(
                id_leitura=leitura.id,
                tipo=TipoAlerta.CONSUMO_ACIMA_LIMITE,
                valor_observado=leitura.consumo_previsto_kwh,
                limite_referencia=limite,
                mensagem=MENSAGEM_CONSUMO.format(
                    previsto=_numero(leitura.consumo_previsto_kwh),
                    limite=_numero(limite),
                    setor=setor.nome,
                    quando=_quando(leitura),
                ),
            )
        )

    if fator_abaixo_do_minimo(leitura):
        alertas.append(
            Alerta(
                id_leitura=leitura.id,
                tipo=TipoAlerta.FATOR_POTENCIA_BAIXO,
                valor_observado=leitura.fator_potencia,
                limite_referencia=FATOR_POTENCIA_MINIMO,
                mensagem=MENSAGEM_FATOR.format(
                    fator=_numero(leitura.fator_potencia), quando=_quando(leitura)
                ),
            )
        )

    return alertas


def abrir_para(leitura: Leitura) -> list[Alerta]:
    """Avalia a leitura e grava os alertas que ela abrir."""
    alertas = avaliar(leitura)
    if not alertas:
        return []
    return alerta_repository.salvar_varios(alertas)


def abrir_para_varias(leituras: list[Leitura]) -> list[Alerta]:
    """O mesmo para um lote inteiro, num commit so (issue #19).

    A importacao de CSV passa por aqui: abrir alerta por alerta, com um commit
    cada, custaria mais que importar as leituras.
    """
    alertas = [alerta for leitura in leituras for alerta in avaliar(leitura)]
    if not alertas:
        return []
    return alerta_repository.salvar_varios(alertas)


# ---------------------------------------------------------------------------
# Issue #28 — a tela do gestor
# ---------------------------------------------------------------------------


def listar(
    tipo: str | None = None,
    status: str | None = None,
    id_setor: int | None = None,
    pagina: int = 1,
) -> dict:
    """Alertas filtrados e paginados, com o que a tela precisa para desenhar.

    Os filtros chegam como texto da query string e sao convertidos aqui: valor
    desconhecido vira None, isto e, "sem filtro", em vez de erro. Uma URL
    editada a mao nao pode quebrar a tela.
    """
    pagina = max(1, pagina)
    alertas, total = alerta_repository.listar(
        tipo=_para_enum(TipoAlerta, tipo),
        status=_para_enum(StatusAlerta, status),
        id_setor=id_setor,
        pagina=pagina,
        por_pagina=POR_PAGINA,
    )
    ultima = max(1, -(-total // POR_PAGINA))  # divisao para cima

    return {
        "alertas": alertas,
        "total": total,
        "pagina": pagina,
        "ultima_pagina": ultima,
        "por_pagina": POR_PAGINA,
        "totais": alerta_repository.contar_por_tipo_e_status(),
    }


def resolver(id_alerta: int, observacao: str, usuario) -> tuple[Alerta | None, list[str]]:
    """Regra 7: o GESTOR marca o alerta como resolvido. Devolve (alerta, erros).

    A observacao e obrigatoria — criterio da #28 e tambem do CHECK do banco. Um
    alerta resolvido sem explicacao nao serve a auditoria, que e justamente para
    que `resolvido_em` e `id_usuario_resolucao` existem.
    """
    alerta = alerta_repository.buscar_por_id(id_alerta)
    if alerta is None:
        return None, ["Alerta não encontrado."]
    if alerta.status == StatusAlerta.RESOLVIDO:
        return None, ["Este alerta já foi resolvido."]

    texto = (observacao or "").strip()
    if len(texto) < OBSERVACAO_MINIMA:
        return None, [
            "Escreva o que foi feito para resolver o alerta "
            f"(pelo menos {OBSERVACAO_MINIMA} caracteres)."
        ]
    if len(texto) > TAMANHO_DA_OBSERVACAO:
        return None, [
            f"A observação pode ter no máximo {TAMANHO_DA_OBSERVACAO} caracteres."
        ]

    alerta.status = StatusAlerta.RESOLVIDO
    alerta.resolvido_em = datetime.now().replace(microsecond=0)
    alerta.id_usuario_resolucao = usuario.id
    alerta.observacao_resolucao = texto
    return alerta_repository.salvar(alerta), []


def _para_enum(classe, valor: str | None):
    """Texto da query string -> enum. Valor desconhecido vira None (sem filtro)."""
    if not valor:
        return None
    try:
        return classe(valor)
    except ValueError:
        return None


def _quando(leitura: Leitura) -> str:
    """Data e hora como se le em portugues."""
    return leitura.data_hora.strftime("%d/%m/%Y às %H:%M")


def _numero(valor: Decimal) -> str:
    """Numero com virgula e sem zeros a direita, como se escreve em portugues."""
    texto = f"{valor:f}"
    if "." in texto:
        texto = texto.rstrip("0").rstrip(".")
    return texto.replace(".", ",")
