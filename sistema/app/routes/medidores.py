"""Blueprint de medidores (issue #17).

A rota valida o formulario, chama o service e devolve o template. Nenhuma regra
de negocio aqui.

Regra 7: como nos setores, o OPERADOR **ve** a lista — precisa saber em que
medidor esta registrando leitura — mas so o GESTOR cadastra, edita e desativa.
"""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ..services import medidor_service
from ..services.auth_service import somente_gestor

bp = Blueprint("medidores", __name__, url_prefix="/medidores")


@bp.route("/")
@login_required
def lista():
    """Lista todos os medidores, ativos e desativados, com o setor de cada um."""
    medidores = medidor_service.listar()
    leituras = {m.id: medidor_service.contar_leituras(m.id) for m in medidores}
    return render_template("medidores/lista.html", medidores=medidores, leituras=leituras)


@bp.route("/novo", methods=["GET", "POST"])
@somente_gestor
def novo():
    """Cadastro de medidor. Só GESTOR."""
    if request.method == "POST":
        medidor, erros = medidor_service.criar(_do_formulario())
        if erros:
            for erro in erros:
                flash(erro, "erro")
            return _tela_do_formulario(None, _do_formulario()), 400

        flash(f"Medidor “{medidor.codigo}” cadastrado.", "sucesso")
        return redirect(url_for("medidores.lista"))

    return _tela_do_formulario(None, {})


@bp.route("/<int:id_medidor>/editar", methods=["GET", "POST"])
@somente_gestor
def editar(id_medidor: int):
    """Edição de medidor. Só GESTOR."""
    medidor = medidor_service.buscar(id_medidor)
    if medidor is None:
        flash("Medidor não encontrado.", "erro")
        return redirect(url_for("medidores.lista"))

    if request.method == "POST":
        atualizado, erros = medidor_service.atualizar(id_medidor, _do_formulario())
        if erros:
            for erro in erros:
                flash(erro, "erro")
            return _tela_do_formulario(medidor, _do_formulario()), 400

        flash(f"Medidor “{atualizado.codigo}” atualizado.", "sucesso")
        return redirect(url_for("medidores.lista"))

    return _tela_do_formulario(medidor, _de_medidor(medidor))


@bp.route("/<int:id_medidor>/alternar-ativo", methods=["POST"])
@somente_gestor
def alternar_ativo(id_medidor: int):
    """Desativa ou reativa. Não apaga leitura nenhuma."""
    medidor, erro = medidor_service.alternar_ativo(id_medidor)
    if erro:
        flash(erro, "erro")
    else:
        estado = "reativado" if medidor.ativo else "desativado"
        flash(f"Medidor “{medidor.codigo}” {estado}.", "sucesso")
    return redirect(url_for("medidores.lista"))


def _tela_do_formulario(medidor, dados: dict):
    """Monta o formulario com a lista de setores que podem ser escolhidos."""
    return render_template(
        "medidores/formulario.html",
        medidor=medidor,
        dados=dados,
        setores=medidor_service.setores_para_escolha(medidor),
    )


def _do_formulario() -> dict:
    """Le os campos enviados, sem interpretar nada."""
    return {
        "codigo": request.form.get("codigo", ""),
        "descricao": request.form.get("descricao", ""),
        "id_setor": request.form.get("id_setor", ""),
    }


def _de_medidor(medidor) -> dict:
    return {
        "codigo": medidor.codigo,
        "descricao": medidor.descricao or "",
        "id_setor": str(medidor.id_setor),
    }
