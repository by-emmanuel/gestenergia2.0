"""Blueprint de alertas (issue #28).

A rota le os filtros, chama o service e devolve o template. Nenhuma regra de
negocio aqui.

Regra 7: **listar** alerta vale para os dois perfis — o operador precisa ver o
que esta aberto no chao de fabrica. **Resolver** e so do GESTOR.
"""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..models import StatusAlerta, TipoAlerta
from ..services import alerta_service, setor_service
from ..services.auth_service import somente_gestor

bp = Blueprint("alertas", __name__, url_prefix="/alertas")


@bp.route("/")
@login_required
def lista():
    """Alertas com filtro por tipo, por status e por setor, paginados."""
    pagina = alerta_service.listar(
        tipo=request.args.get("tipo"),
        status=request.args.get("status"),
        id_setor=_inteiro(request.args.get("setor")),
        pagina=_inteiro(request.args.get("pagina")) or 1,
    )
    return render_template(
        "alertas/lista.html",
        **pagina,
        setores=setor_service.listar(),
        filtros={
            "tipo": request.args.get("tipo", ""),
            "status": request.args.get("status", ""),
            "setor": request.args.get("setor", ""),
        },
        tipos=list(TipoAlerta),
        status_possiveis=list(StatusAlerta),
    )


@bp.route("/<int:id_alerta>/resolver", methods=["POST"])
@login_required
@somente_gestor
def resolver(id_alerta: int):
    """Regra 7: só o GESTOR resolve alerta."""
    alerta, erros = alerta_service.resolver(
        id_alerta, request.form.get("observacao", ""), current_user
    )
    if erros:
        for erro in erros:
            flash(erro, "erro")
    else:
        flash(f"Alerta #{alerta.id} marcado como resolvido.", "sucesso")

    # Volta para a mesma pagina e os mesmos filtros de onde o gestor veio: quem
    # resolve alerta resolve varios seguidos, e cair na primeira pagina sem
    # filtro a cada resolucao tornaria a tela insuportavel com 400 por semana.
    return redirect(request.form.get("voltar_para") or url_for("alertas.lista"))


def _inteiro(bruto: str | None) -> int | None:
    """Numero da query string, ou None se vier vazio ou invalido."""
    try:
        return int(bruto)
    except (TypeError, ValueError):
        return None
