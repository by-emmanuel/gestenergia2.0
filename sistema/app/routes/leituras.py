"""Blueprint de leituras (issues #18 e #19).

A rota valida o formulario, chama o service e devolve o template. Nenhuma regra
de negocio aqui.

Regra 7: OPERADOR **e** GESTOR registram e importam leitura — e a atividade
principal do operador. Nao ha restricao de perfil nestas telas.
"""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ..services import importacao_service, leitura_service, medidor_service

bp = Blueprint("leituras", __name__, url_prefix="/leituras")

QUANTIDADE_NA_LISTA = 50
# Teto do arquivo enviado. Um ano de um medidor da uns 2,6 MB no formato da
# siderurgica; 20 MB deixam folga larga sem aceitar um envio absurdo.
TAMANHO_MAXIMO_MB = 20


@bp.route("/")
@login_required
def lista():
    """Últimas leituras registradas, da mais recente para a mais antiga."""
    leituras = leitura_service.listar_recentes(QUANTIDADE_NA_LISTA)
    return render_template(
        "leituras/lista.html",
        leituras=leituras,
        total=leitura_service.contar(),
        quantidade_na_lista=QUANTIDADE_NA_LISTA,
        # Quem decide se o fator viola a regra 1 e o service, nunca o template:
        # comparar Decimal com float marca exatamente 0,92 como violacao.
        fator_baixo={l.id: leitura_service.fator_abaixo_do_minimo(l) for l in leituras},
        fator_minimo=leitura_service.FATOR_POTENCIA_MINIMO,
    )


@bp.route("/nova", methods=["GET", "POST"])
@login_required
def nova():
    """Registro manual de leitura. Operador e gestor."""
    if request.method == "POST":
        leitura, erros = leitura_service.registrar(_do_formulario())
        if erros:
            for erro in erros:
                flash(erro, "erro")
            return _tela_do_formulario(_do_formulario()), 400

        flash(
            f"Leitura de {leitura.data_hora.strftime('%d/%m/%Y às %H:%M')} registrada.",
            "sucesso",
        )
        # Volta ao formulario com o medidor mantido: quem registra leitura
        # normalmente registra varias do mesmo medidor em sequencia.
        return redirect(url_for("leituras.nova", id_medidor=leitura.id_medidor))

    return _tela_do_formulario({"id_medidor": request.args.get("id_medidor", "")})


@bp.route("/importar", methods=["GET", "POST"])
@login_required
def importar():
    """Importacao de leituras por CSV (issue #19). Operador e gestor."""
    medidores = medidor_service.listar(apenas_ativos=True)

    if request.method == "POST":
        id_medidor = request.form.get("id_medidor", "")
        arquivo = request.files.get("arquivo")

        conteudo, erro = _ler_arquivo(arquivo)
        if erro:
            flash(erro, "erro")
            return render_template(
                "leituras/importar.html", medidores=medidores, dados={"id_medidor": id_medidor}
            ), 400

        resultado = importacao_service.importar(_medidor_escolhido(id_medidor), conteudo)
        for mensagem in resultado.erros:
            flash(mensagem, "erro")

        return render_template(
            "leituras/importar.html",
            medidores=medidores,
            dados={"id_medidor": id_medidor},
            resultado=resultado,
        ), (200 if resultado.deu_certo else 400)

    return render_template(
        "leituras/importar.html",
        medidores=medidores,
        dados={"id_medidor": request.args.get("id_medidor", "")},
    )


def _medidor_escolhido(id_medidor: str):
    """O medidor do formulario, ou None se vier vazio ou nao numerico."""
    try:
        return medidor_service.buscar(int(id_medidor))
    except (TypeError, ValueError):
        return None


def _ler_arquivo(arquivo) -> tuple[str, str | None]:
    """Le o CSV enviado. Devolve (conteudo, erro).

    O `utf-8-sig` e obrigatorio: o CSV da siderurgica vem **com BOM**, e sem
    isso a primeira coluna se chamaria "﻿date" e o formato nao seria
    reconhecido.
    """
    if arquivo is None or not arquivo.filename:
        return "", "Escolha o arquivo CSV."

    bruto = arquivo.read()
    if len(bruto) > TAMANHO_MAXIMO_MB * 1024 * 1024:
        return "", f"O arquivo passa de {TAMANHO_MAXIMO_MB} MB. Envie um trecho menor."

    for codificacao in ("utf-8-sig", "latin-1"):
        try:
            return bruto.decode(codificacao), None
        except UnicodeDecodeError:
            continue
    return "", "Não consegui ler o arquivo: ele não parece ser um CSV de texto."


def _tela_do_formulario(dados: dict):
    """Monta o formulario com os medidores ativos que podem receber leitura."""
    return render_template(
        "leituras/formulario.html",
        dados=dados,
        medidores=medidor_service.listar(apenas_ativos=True),
    )


def _do_formulario() -> dict:
    """Le os campos enviados, sem interpretar nada."""
    return {
        "id_medidor": request.form.get("id_medidor", ""),
        "data_hora": request.form.get("data_hora", ""),
        "consumo_kwh": request.form.get("consumo_kwh", ""),
        "fator_potencia": request.form.get("fator_potencia", ""),
    }
