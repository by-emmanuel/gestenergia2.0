"""Blueprint de setores (issue #16).

A rota valida o formulario, chama o service e devolve o template. Nenhuma regra
de negocio aqui.

Regra 7: OPERADOR **ve** a lista, porque precisa saber em que setor esta
registrando leitura, mas so o GESTOR cadastra, edita e desativa.
"""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ..services import setor_service
from ..services.auth_service import somente_gestor

bp = Blueprint("setores", __name__, url_prefix="/setores")


@bp.route("/")
@login_required
def lista():
    """Lista todos os setores, ativos e desativados."""
    setores = setor_service.listar()
    medidores_por_setor = {s.id: setor_service.contar_medidores(s.id) for s in setores}
    return render_template("setores/lista.html", setores=setores, medidores=medidores_por_setor)


@bp.route("/novo", methods=["GET", "POST"])
@somente_gestor
def novo():
    """Cadastro de setor. Só GESTOR."""
    if request.method == "POST":
        setor, erros = setor_service.criar(_do_formulario())
        if erros:
            for erro in erros:
                flash(erro, "erro")
            return render_template("setores/formulario.html", setor=None, dados=_do_formulario()), 400

        flash(f"Setor “{setor.nome}” cadastrado.", "sucesso")
        return redirect(url_for("setores.lista"))

    return render_template("setores/formulario.html", setor=None, dados={})


@bp.route("/<int:id_setor>/editar", methods=["GET", "POST"])
@somente_gestor
def editar(id_setor: int):
    """Edição de setor, inclusive o limite de consumo. Só GESTOR (regra 7)."""
    setor = setor_service.buscar(id_setor)
    if setor is None:
        flash("Setor não encontrado.", "erro")
        return redirect(url_for("setores.lista"))

    if request.method == "POST":
        atualizado, erros = setor_service.atualizar(id_setor, _do_formulario())
        if erros:
            for erro in erros:
                flash(erro, "erro")
            return (
                render_template("setores/formulario.html", setor=setor, dados=_do_formulario()),
                400,
            )

        flash(f"Setor “{atualizado.nome}” atualizado.", "sucesso")
        return redirect(url_for("setores.lista"))

    return render_template("setores/formulario.html", setor=setor, dados=_de_setor(setor))


@bp.route("/<int:id_setor>/alternar-ativo", methods=["POST"])
@somente_gestor
def alternar_ativo(id_setor: int):
    """Desativa ou reativa. Desativar não apaga histórico nenhum."""
    setor, erro = setor_service.alternar_ativo(id_setor)
    if erro:
        flash(erro, "erro")
    else:
        estado = "reativado" if setor.ativo else "desativado"
        flash(f"Setor “{setor.nome}” {estado}.", "sucesso")
    return redirect(url_for("setores.lista"))


def _do_formulario() -> dict:
    """Le os campos enviados, sem interpretar nada."""
    return {
        "nome": request.form.get("nome", ""),
        "descricao": request.form.get("descricao", ""),
        "limite_consumo_kwh": request.form.get("limite_consumo_kwh", ""),
        "arquivo_modelo": request.form.get("arquivo_modelo", ""),
        "tem_fator_potencia": request.form.get("tem_fator_potencia") is not None,
    }


def _de_setor(setor) -> dict:
    """Preenche o formulario a partir do setor guardado."""
    limite = setor.limite_consumo_kwh
    return {
        "nome": setor.nome,
        "descricao": setor.descricao or "",
        # Mostra com virgula, que e como se digita em portugues.
        "limite_consumo_kwh": ("" if limite is None else f"{limite:.3f}".replace(".", ",")),
        "arquivo_modelo": setor.arquivo_modelo or "",
        "tem_fator_potencia": setor.tem_fator_potencia,
    }
