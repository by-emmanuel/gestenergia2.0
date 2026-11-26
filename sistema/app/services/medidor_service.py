"""Regras de negocio dos medidores (issue #17).

Todas as validacoes moram aqui, nunca na rota e nunca no template.

Os dois critérios da issue:

  - **codigo unico** (espelha uq_medidor_codigo). O codigo e normalizado para
    MAIUSCULAS, porque a colacao do MySQL ja ignora maiusculas: sem normalizar,
    "med-prod" seria recusado como repetido de "MED-PROD" mas ficaria gravado
    com a grafia que o usuario digitou, e a lista pareceria inconsistente.

  - **medidor sempre ligado a um setor ativo.** A regra vale na ESCRITA: nao se
    cadastra, nem se move, medidor para setor desativado. Na LEITURA o vinculo
    antigo e preservado, porque desativar setor nao apaga historico (issue #16):
    um medidor pode continuar apontando para um setor que foi desativado depois,
    e a tela avisa. Sem essa distincao, desativar um setor tornaria os medidores
    dele impossiveis de editar.
"""

from ..models import Medidor
from ..repositories import medidor_repository, setor_repository

TAMANHO_CODIGO = 60
TAMANHO_DESCRICAO = 255


def listar(apenas_ativos: bool = False) -> list[Medidor]:
    return medidor_repository.listar(apenas_ativos=apenas_ativos)


def buscar(id_medidor: int) -> Medidor | None:
    return medidor_repository.buscar_por_id(id_medidor)


def contar_leituras(id_medidor: int) -> int:
    return medidor_repository.contar_leituras(id_medidor)


def setores_para_escolha(medidor: Medidor | None = None) -> list:
    """Setores que podem ser escolhidos no formulario.

    Os ativos, mais o setor atual do medidor quando ele ja foi desativado — para
    a edicao nao perder o vinculo nem obrigar a trocar de setor sem necessidade.
    """
    setores = setor_repository.listar(apenas_ativos=True)
    if medidor is not None and medidor.setor is not None and not medidor.setor.ativo:
        setores = [*setores, medidor.setor]
    return setores


def _normalizar_codigo(bruto: str | None) -> str:
    return (bruto or "").strip().upper()


def _converter_id_setor(bruto) -> tuple[int | None, str | None]:
    """Le o setor escolhido no formulario. Devolve (id, erro)."""
    texto = str(bruto or "").strip()
    if not texto:
        return None, "Escolha o setor do medidor."
    try:
        return int(texto), None
    except ValueError:
        return None, "Setor inválido."


def validar(dados: dict, medidor: Medidor | None = None) -> list[str]:
    """Confere os campos e devolve a lista de erros. Lista vazia significa que passou."""
    erros: list[str] = []

    codigo = _normalizar_codigo(dados.get("codigo"))
    if not codigo:
        erros.append("O código do medidor é obrigatório.")
    elif len(codigo) > TAMANHO_CODIGO:
        erros.append(f"O código do medidor deve ter no máximo {TAMANHO_CODIGO} caracteres.")
    else:
        existente = medidor_repository.buscar_por_codigo(codigo)
        if existente is not None and (medidor is None or existente.id != medidor.id):
            erros.append(f"Já existe um medidor com o código “{existente.codigo}”.")

    if len(dados.get("descricao") or "") > TAMANHO_DESCRICAO:
        erros.append(f"A descrição deve ter no máximo {TAMANHO_DESCRICAO} caracteres.")

    id_setor, erro_setor = _converter_id_setor(dados.get("id_setor"))
    if erro_setor:
        erros.append(erro_setor)
    else:
        setor = setor_repository.buscar_por_id(id_setor)
        if setor is None:
            erros.append("Setor não encontrado.")
        elif not setor.ativo and (medidor is None or medidor.id_setor != setor.id):
            # Vinculo NOVO para setor desativado: barrado. Manter o vinculo que
            # ja existia e permitido, senao o medidor ficaria ineditavel.
            erros.append(
                f"O setor “{setor.nome}” está desativado. "
                "Reative o setor ou escolha outro para este medidor."
            )

    return erros


def _aplicar(medidor: Medidor, dados: dict) -> Medidor:
    id_setor, _ = _converter_id_setor(dados.get("id_setor"))

    medidor.codigo = _normalizar_codigo(dados.get("codigo"))
    medidor.descricao = (dados.get("descricao") or "").strip() or None
    medidor.id_setor = id_setor
    return medidor


def criar(dados: dict) -> tuple[Medidor | None, list[str]]:
    """Cadastra um medidor novo. Devolve (medidor, erros)."""
    erros = validar(dados)
    if erros:
        return None, erros
    return medidor_repository.salvar(_aplicar(Medidor(), dados)), []


def atualizar(id_medidor: int, dados: dict) -> tuple[Medidor | None, list[str]]:
    """Altera um medidor existente. Devolve (medidor, erros)."""
    medidor = medidor_repository.buscar_por_id(id_medidor)
    if medidor is None:
        return None, ["Medidor não encontrado."]

    erros = validar(dados, medidor=medidor)
    if erros:
        return None, erros
    return medidor_repository.salvar(_aplicar(medidor, dados)), []


def alternar_ativo(id_medidor: int) -> tuple[Medidor | None, str | None]:
    """Desativa um medidor ativo, ou reativa um desativado.

    Nao apaga leitura nenhuma: o medidor so deixa de ser oferecido no registro
    de leitura (issue #18).
    """
    medidor = medidor_repository.buscar_por_id(id_medidor)
    if medidor is None:
        return None, "Medidor não encontrado."

    if not medidor.ativo and not medidor.setor.ativo:
        return None, (
            f"O setor “{medidor.setor.nome}” está desativado. "
            "Reative o setor antes de reativar este medidor."
        )

    medidor.ativo = not medidor.ativo
    return medidor_repository.salvar(medidor), None
