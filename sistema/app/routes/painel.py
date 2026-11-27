"""Blueprint do painel (issue #9, versao minima).

Por enquanto a pagina inicial, a conta do usuario autenticado (issue #10) e a
verificacao de saude. O painel de consumo real x previsto e a lista de alertas
sao a issue #20.
"""

import os

from flask import Blueprint, current_app, jsonify, render_template, request, send_from_directory
from flask_login import current_user, login_required

from ..banco import motor
from ..services import painel_service, previsao_service, setor_service
from ..services.saude_service import verificar_banco

bp = Blueprint("painel", __name__)


@bp.route("/")
def inicio():
    """Pagina inicial do sistema. Publica: e a porta de entrada."""
    return render_template("inicio.html")


@bp.route("/favicon.ico")
def favicon():
    """Responde ao pedido automatico do navegador por /favicon.ico.

    As paginas ja apontam para o favicon em static/icones; esta rota so evita
    o 404 nos logs quando o navegador pede o endereco padrao por conta propria.
    """
    pasta = os.path.join(current_app.static_folder, "icones")
    return send_from_directory(pasta, "favicon-32.png", mimetype="image/png")


@bp.route("/conta")
@login_required
def conta():
    """Dados da sessao e o que o perfil do usuario permite (regra 7)."""
    return render_template("conta.html", usuario=current_user)


@bp.route("/painel")
@login_required
def painel():
    """Consumo real x previsto do medidor e alertas abertos do setor (issue #20).

    Os tres filtros (setor, medidor, janela) vem da query string e escopam TUDO
    o que esta abaixo deles: grafico, tabela e alertas leem a mesma fatia.
    """
    setor = painel_service.escolher_setor(request.args.get("setor"))
    medidores = painel_service.medidores_para_o_filtro(setor)
    medidor = painel_service.escolher_medidor(request.args.get("medidor"), medidores)
    janela = request.args.get("janela", painel_service.JANELA_PADRAO)
    quantidade = painel_service.quantidade_da_janela(janela)

    return render_template(
        "painel.html",
        setores=setor_service.listar(),
        setor_escolhido=setor,
        medidores=medidores,
        medidor_escolhido=medidor,
        janelas=painel_service.JANELAS,
        janela_escolhida=janela if any(j[0] == janela for j in painel_service.JANELAS)
        else painel_service.JANELA_PADRAO,
        serie=painel_service.serie(medidor, quantidade),
        tabela=painel_service.tabela(medidor, quantidade),
        alertas=painel_service.alertas_abertos(setor),
        totais_de_alerta=painel_service.totais_de_alerta(setor),
        cor_real=painel_service.COR_REAL,
        cor_previsto=painel_service.COR_PREVISTO,
    )


@bp.route("/saude")
def saude():
    """Diagnostico do ambiente: aplicacao, banco e modelos (issues #9 e #26).

    Serve para conferir o container sem depender de tela nenhuma — e e o
    primeiro comando a rodar na maquina do laboratorio (#41).

    Os modelos entram aqui porque a aplicacao sobe NORMALMENTE sem eles (regra
    9: o setor devolve None e a tela mostra "sem previsao ainda"). Sem esta
    linha, a unica forma de descobrir que ml/ ficou para tras no git clone seria
    registrar cinco leituras e reparar que a previsao nao veio.
    """
    conectou, detalhe = verificar_banco(motor())
    carregados = previsao_service.modelos_carregados()
    corpo = {
        "aplicacao": "ok",
        "banco": "ok" if conectou else "falhou",
        "banco_detalhe": detalhe,
        "nome_do_banco": current_app.config["NOME_DO_BANCO"],
        "modelos": len(carregados),
        "modelos_carregados": carregados,
    }
    return jsonify(corpo), 200 if conectou else 503
