"""Regras de negocio dos setores (issue #16).

Todas as validacoes moram aqui, nunca na rota e nunca no template.

O que esta camada garante, espelhando as restricoes do banco:

  - nome obrigatorio e unico (uq_setor_nome);
  - limite de consumo NULL ou maior que zero (ck_setor_limite_positivo, regra 10);
  - desativar NAO apaga nada: mexe so na coluna ativo, e medidores, leituras e
    alertas do setor continuam no banco.
"""

from decimal import Decimal, InvalidOperation

from ..models import Setor
from ..repositories import setor_repository

TAMANHO_NOME = 120
TAMANHO_DESCRICAO = 255
TAMANHO_ARQUIVO_MODELO = 120


def listar(apenas_ativos: bool = False) -> list[Setor]:
    return setor_repository.listar(apenas_ativos=apenas_ativos)


def buscar(id_setor: int) -> Setor | None:
    return setor_repository.buscar_por_id(id_setor)


def contar_medidores(id_setor: int) -> int:
    return setor_repository.contar_medidores(id_setor)


def converter_limite(bruto: str | None) -> tuple[Decimal | None, str | None]:
    """Le o limite digitado no formulario.

    Devolve (valor, erro). Vazio devolve (None, None): limite NULL e valido e
    significa que o setor NAO gera alerta de consumo ate a issue #44 calcular o
    percentil 99 (regra 10).

    Aceita virgula como separador decimal, porque e o que se digita em portugues
    e e o que as bases usam.
    """
    if bruto is None:
        return None, None

    texto = str(bruto).strip().replace(" ", "")
    if not texto:
        return None, None

    try:
        valor = Decimal(texto.replace(",", "."))
    except InvalidOperation:
        return None, "O limite de consumo precisa ser um número (ex.: 122,71)."

    if valor <= 0:
        return None, "O limite de consumo precisa ser maior que zero."
    return valor, None


def validar(dados: dict, id_existente: int | None = None) -> list[str]:
    """Confere os campos do formulario e devolve a lista de erros.

    Lista vazia significa que passou. `id_existente` evita que o setor acuse
    nome repetido contra si mesmo na edicao.
    """
    erros: list[str] = []

    nome = (dados.get("nome") or "").strip()
    if not nome:
        erros.append("O nome do setor é obrigatório.")
    elif len(nome) > TAMANHO_NOME:
        erros.append(f"O nome do setor deve ter no máximo {TAMANHO_NOME} caracteres.")
    else:
        existente = setor_repository.buscar_por_nome(nome)
        if existente is not None and existente.id != id_existente:
            erros.append(f"Já existe um setor chamado “{existente.nome}”.")

    if len(dados.get("descricao") or "") > TAMANHO_DESCRICAO:
        erros.append(f"A descrição deve ter no máximo {TAMANHO_DESCRICAO} caracteres.")

    if len(dados.get("arquivo_modelo") or "") > TAMANHO_ARQUIVO_MODELO:
        erros.append(
            f"O arquivo do modelo deve ter no máximo {TAMANHO_ARQUIVO_MODELO} caracteres."
        )

    _, erro_limite = converter_limite(dados.get("limite_consumo_kwh"))
    if erro_limite:
        erros.append(erro_limite)

    return erros


def _aplicar(setor: Setor, dados: dict) -> Setor:
    """Copia os campos do formulario para o setor, ja normalizados."""
    limite, _ = converter_limite(dados.get("limite_consumo_kwh"))

    setor.nome = (dados.get("nome") or "").strip()
    setor.descricao = (dados.get("descricao") or "").strip() or None
    setor.arquivo_modelo = (dados.get("arquivo_modelo") or "").strip() or None
    setor.limite_consumo_kwh = limite
    setor.tem_fator_potencia = bool(dados.get("tem_fator_potencia"))
    return setor


def criar(dados: dict) -> tuple[Setor | None, list[str]]:
    """Cadastra um setor novo. Devolve (setor, erros)."""
    erros = validar(dados)
    if erros:
        return None, erros
    return setor_repository.salvar(_aplicar(Setor(), dados)), []


def atualizar(id_setor: int, dados: dict) -> tuple[Setor | None, list[str]]:
    """Altera um setor existente. Devolve (setor, erros)."""
    setor = setor_repository.buscar_por_id(id_setor)
    if setor is None:
        return None, ["Setor não encontrado."]

    erros = validar(dados, id_existente=setor.id)
    if erros:
        return None, erros
    return setor_repository.salvar(_aplicar(setor, dados)), []


def alternar_ativo(id_setor: int) -> tuple[Setor | None, str | None]:
    """Desativa um setor ativo, ou reativa um desativado.

    Desativar NAO apaga histórico: medidores, leituras e alertas continuam no
    banco. O setor so deixa de aparecer onde se escolhe setor para cadastrar.
    """
    setor = setor_repository.buscar_por_id(id_setor)
    if setor is None:
        return None, "Setor não encontrado."

    setor.ativo = not setor.ativo
    return setor_repository.salvar(setor), None
