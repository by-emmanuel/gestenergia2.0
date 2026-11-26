"""O fluxo completo do sistema, de ponta a ponta (issue #24).

Exige o banco de pé:  docker compose up -d db

Este arquivo tem **um** teste que importa de verdade: `test_o_fluxo_completo`,
que percorre a cadeia inteira num único teste, sem atalho e sem semear nada pelo
ORM — tudo passa pelas telas, como a pessoa faz.

    entrar  ->  cadastrar setor  ->  cadastrar medidor  ->  importar leituras
            ->  o painel mostra o previsto e o alerta
            ->  o gestor resolve  ->  o alerta sai dos abertos

Os outros arquivos de `tests/system/` cobrem cada etapa em profundidade, com os
casos de borda. O valor **deste** é outro: ele é o roteiro da apresentação. Se
ele passa, a demonstração passa; se quebrar, quebra aqui em vez de na frente do
professor.

Usa os `.pkl` de verdade de `ml/`, porque previsão e alerta fazem parte do que
se quer provar.
"""

import io
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Alerta, Leitura, Medidor, Setor, StatusAlerta, TipoAlerta
from app.services import previsao_service
from tests.conftest import SENHA_GESTOR, SENHA_OPERADOR

# Quarta-feira, 3 de janeiro de 2018 — o mesmo período dos dados da demonstração.
PRIMEIRA = datetime(2018, 1, 3, 0, 0)
MODELO_DA_PRODUCAO = "modelo_consumo_producao.pkl"
# Um dia de leituras: 96 períodos de 15 minutos.
PERIODOS = 96


@pytest.fixture(autouse=True)
def modelos_de_verdade(app):
    previsao_service.carregar_modelos(app.config["CAMINHO_MODELO"])
    if MODELO_DA_PRODUCAO not in previsao_service.modelos_carregados():
        pytest.skip("ml/ sem os modelos: rode notebooks/salvar_modelos.py (issue #25)")


def entrar(cliente, email, senha):
    return cliente.post(
        "/login", data={"email": email, "senha": senha}, follow_redirects=True
    )


def csv_de_um_dia(consumo_base=60.0, fator="70.00"):
    """Um dia de leituras no formato da siderúrgica, com fator de potência baixo.

    O consumo sobe e desce ao longo do dia para a previsão ter o que seguir, e o
    fator fica abaixo de 0,92 para o alerta da regra 1 abrir.
    """
    cabecalho = (
        "date,Usage_kWh,Lagging_Current_Reactive.Power_kVarh,"
        "Leading_Current_Reactive_Power_kVarh,CO2(tCO2),Lagging_Current_Power_Factor,"
        "Leading_Current_Power_Factor,NSM,WeekStatus,Day_of_week,Load_Type"
    )
    linhas = [cabecalho]
    for passo in range(PERIODOS):
        quando = PRIMEIRA + timedelta(minutes=15 * passo)
        # Sobe até o meio do dia e desce depois.
        consumo = consumo_base + (passo if passo < PERIODOS // 2 else PERIODOS - passo)
        linhas.append(
            f"{quando.strftime('%d/%m/%Y %H:%M')},{consumo:.2f},2.95,0,0,"
            f"{fator},100,{passo * 900},Weekday,Wednesday,Medium_Load"
        )
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# O fluxo completo — o critério da #24
# ---------------------------------------------------------------------------


def test_o_fluxo_completo(cliente, usuarios, sessao, recarregar):
    """Login → setor → medidor → leituras → alerta no painel → gestor resolve.

    Um teste só, de propósito: o que se quer provar é que as etapas se ligam.
    Dividir em seis testes com fixtures provaria as etapas, não a ligação.
    """
    # --- 1. o gestor entra --------------------------------------------------
    resposta = entrar(cliente, "gestor@gestenergia.local", SENHA_GESTOR)
    assert resposta.status_code == 200
    assert "Gestor de Energia" in resposta.get_data(as_text=True)

    # --- 2. cadastra o setor, com limite e modelo ---------------------------
    resposta = cliente.post(
        "/setores/novo",
        data={
            "nome": "Fundição",
            "descricao": "Setor criado pelo teste de ponta a ponta",
            "limite_consumo_kwh": "122,980",
            "arquivo_modelo": MODELO_DA_PRODUCAO,
            "tem_fator_potencia": "on",
        },
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    recarregar()
    setor = sessao.scalar(select(Setor).where(Setor.nome == "Fundição"))
    assert setor is not None, "o setor não foi criado pela tela"
    assert setor.limite_consumo_kwh == Decimal("122.980")
    assert setor.arquivo_modelo == MODELO_DA_PRODUCAO

    # --- 3. cadastra o medidor naquele setor --------------------------------
    resposta = cliente.post(
        "/medidores/novo",
        data={
            "codigo": "MED-FUND",
            "descricao": "Medidor principal da fundição",
            "id_setor": str(setor.id),
        },
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    recarregar()
    medidor = sessao.scalar(select(Medidor).where(Medidor.codigo == "MED-FUND"))
    assert medidor is not None, "o medidor não foi criado pela tela"
    assert medidor.id_setor == setor.id

    # --- 4. importa um dia de leituras --------------------------------------
    resposta = cliente.post(
        "/leituras/importar",
        data={
            "id_medidor": str(medidor.id),
            "arquivo": (io.BytesIO(csv_de_um_dia().encode("utf-8")), "fundicao.csv"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    recarregar()
    leituras = list(sessao.scalars(select(Leitura).order_by(Leitura.data_hora)))
    assert len(leituras) == PERIODOS

    # Regra 4: as 4 primeiras sem previsão, o resto com.
    assert [l.consumo_previsto_kwh for l in leituras[:4]] == [None] * 4
    assert all(l.consumo_previsto_kwh is not None for l in leituras[4:])

    # Regra 6: o fator veio em percentual no CSV e foi guardado de 0 a 1.
    assert leituras[0].fator_potencia == Decimal("0.700")

    # --- 5. os alertas foram abertos ----------------------------------------
    recarregar()
    alertas = list(sessao.scalars(select(Alerta)))
    assert alertas, "a importação não abriu nenhum alerta"
    assert TipoAlerta.FATOR_POTENCIA_BAIXO in {a.tipo for a in alertas}
    assert all(a.status == StatusAlerta.ABERTO for a in alertas)

    # --- 6. o painel mostra o consumo previsto e os alertas -----------------
    painel = cliente.get("/painel").get_data(as_text=True)
    assert "Consumo previsto" in painel
    assert "sem previsão ainda" not in painel
    assert "Alertas abertos" in painel

    # --- 7. a tela de alertas lista o que foi aberto ------------------------
    tela = cliente.get("/alertas/?status=ABERTO").get_data(as_text=True)
    assert "MED-FUND" in tela
    assert "Fator de potência baixo" in tela

    # --- 8. o gestor resolve um alerta --------------------------------------
    alvo = alertas[0]
    resposta = cliente.post(
        f"/alertas/{alvo.id}/resolver",
        data={"observacao": "Banco de capacitores religado na fundição"},
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    recarregar()
    resolvido = sessao.get(Alerta, alvo.id)
    assert resolvido.status == StatusAlerta.RESOLVIDO
    assert resolvido.observacao_resolucao == "Banco de capacitores religado na fundição"
    assert resolvido.resolvido_em is not None
    assert resolvido.id_usuario_resolucao == usuarios["gestor"].id

    # --- 9. o resolvido sai dos abertos e aparece nos resolvidos ------------
    abertos = cliente.get("/alertas/?status=ABERTO").get_data(as_text=True)
    resolvidos = cliente.get("/alertas/?status=RESOLVIDO").get_data(as_text=True)
    assert "Banco de capacitores religado" not in abertos
    assert "Banco de capacitores religado" in resolvidos


# ---------------------------------------------------------------------------
# Regra 7 — o segundo critério da #24
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "caminho, dados",
    [
        ("/setores/novo", {"nome": "Setor do operador"}),
        ("/medidores/novo", {"codigo": "MED-OP", "id_setor": "1"}),
    ],
)
def test_operador_e_barrado_nas_telas_do_gestor(cliente, usuarios, caminho, dados):
    """Regra 7: só o GESTOR mantém setores e medidores.

    Testa o POST, e não só o GET: esconder o formulário não é controle de acesso.
    """
    entrar(cliente, "operador@gestenergia.local", SENHA_OPERADOR)

    assert cliente.get(caminho).status_code == 403
    assert cliente.post(caminho, data=dados).status_code == 403


def test_operador_faz_o_que_e_dele(cliente, usuarios, sessao, recarregar):
    """O outro lado da regra 7: registrar e importar leitura é a atividade dele."""
    setor = Setor(nome="Fundição", arquivo_modelo=MODELO_DA_PRODUCAO)
    medidor = Medidor(setor=setor, codigo="MED-FUND")
    sessao.add(medidor)
    sessao.commit()

    entrar(cliente, "operador@gestenergia.local", SENHA_OPERADOR)

    assert cliente.get("/painel").status_code == 200
    assert cliente.get("/leituras/nova").status_code == 200
    assert cliente.get("/leituras/importar").status_code == 200
    assert cliente.get("/alertas/").status_code == 200

    resposta = cliente.post(
        "/leituras/nova",
        data={
            "id_medidor": str(medidor.id),
            "data_hora": PRIMEIRA.strftime("%Y-%m-%dT%H:%M"),
            "consumo_kwh": "42,5",
            "fator_potencia": "",
        },
        follow_redirects=True,
    )

    assert resposta.status_code == 200
    recarregar()
    assert len(list(sessao.scalars(select(Leitura)))) == 1


def test_operador_nao_resolve_alerta(cliente, usuarios, sessao, recarregar):
    """Resolver é do gestor, mesmo o operador podendo ver a lista."""
    setor = Setor(nome="Fundição")
    medidor = Medidor(setor=setor, codigo="MED-FUND")
    leitura = Leitura(
        medidor=medidor, data_hora=PRIMEIRA, consumo_kwh=Decimal("10"),
        fator_potencia=Decimal("0.700"),
    )
    alerta = Alerta(
        leitura=leitura,
        tipo=TipoAlerta.FATOR_POTENCIA_BAIXO,
        valor_observado=Decimal("0.700"),
        limite_referencia=Decimal("0.920"),
    )
    sessao.add(alerta)
    sessao.commit()
    id_alerta = alerta.id

    entrar(cliente, "operador@gestenergia.local", SENHA_OPERADOR)
    resposta = cliente.post(
        f"/alertas/{id_alerta}/resolver", data={"observacao": "Tentando resolver"}
    )

    assert resposta.status_code == 403
    recarregar()
    assert sessao.get(Alerta, id_alerta).status == StatusAlerta.ABERTO
