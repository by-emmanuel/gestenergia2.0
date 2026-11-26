"""Importacao de leituras por CSV (issue #19).

Aceita os DOIS formatos que o projeto tem, detectados pelo cabecalho, sem o
usuario escolher:

  - **siderurgica** — o `Steel_industry_data.csv` original da UCI, com as 11
    colunas, data em DD/MM/AAAA HH:MM e fator de potencia EM PERCENTUAL;
  - **setor** — os CSVs de `data/setores/` gerados pela #44, com `date` e
    `Usage_kWh` so, data em ISO e sem fator de potencia.

Tres armadilhas desta importacao, todas documentadas em docs/bases-de-dados.md:

  1. **A siderurgica nao esta em ordem cronologica**: a linha das 00:00 vem no
     fim de cada dia, 729 vezes no ano. Importar na ordem do arquivo corromperia
     os lags, entao as linhas sao ORDENADAS antes de qualquer coisa.
  2. **O fator de potencia da siderurgica vem em percentual** (73,21) e a regra 6
     manda guardar de 0 a 1 (0,7321). A conversao e aqui.
  3. **Os dois formatos de data convivem**: ISO num, DD/MM/AAAA no outro. Por
     isso o formato e detectado pelo cabecalho e cada um usa o seu leitor.

Sobre gravar em lote em vez de chamar `leitura_service.registrar` em laco: as
REGRAS continuam num lugar so — as conversoes e as validacoes sao as mesmas
funcoes do `leitura_service`, e previsao e alerta sao os mesmos servicos. O que
muda e so a gravacao, que vai num commit em vez de um por linha. Um ano inteiro
sao 35.040 linhas; com um commit por linha a importacao levaria minutos e
prenderia a transacao do banco o tempo todo.
"""

import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation

from ..models import Leitura
from ..repositories import leitura_repository
from . import alerta_service, previsao_service
from .leitura_service import converter_consumo

# O cabecalho de cada formato. A deteccao olha as colunas, nao o nome do arquivo.
COLUNA_DATA = "date"
COLUNA_CONSUMO = "Usage_kWh"
COLUNA_FATOR = "Lagging_Current_Power_Factor"

FORMATO_SIDERURGICA = "siderurgica"
FORMATO_SETOR = "setor"

# Regra 6: na base da siderurgica o fator vem de 0 a 100.
DIVISOR_DO_PERCENTUAL = Decimal("100")

# Teto de seguranca. Um ano inteiro de um medidor sao 35.040 linhas; o dobro
# disso num arquivo so e quase certamente engano, e a tela avisa em vez de
# deixar a requisicao pendurada.
MAXIMO_DE_LINHAS = 70_000

FORMATOS_DE_DATA = {
    FORMATO_SIDERURGICA: ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"),
    FORMATO_SETOR: ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"),
}


class Resultado:
    """O que a tela mostra depois de importar."""

    def __init__(self):
        self.formato: str | None = None
        self.importadas: int = 0
        self.ignoradas: int = 0
        self.alertas: int = 0
        self.com_previsao: int = 0
        self.primeira: datetime | None = None
        self.ultima: datetime | None = None
        self.motivos: dict[str, int] = {}
        self.erros: list[str] = []

    def ignorar(self, motivo: str) -> None:
        self.ignoradas += 1
        self.motivos[motivo] = self.motivos.get(motivo, 0) + 1

    @property
    def deu_certo(self) -> bool:
        return not self.erros and self.importadas > 0


def detectar_formato(colunas) -> str | None:
    """Qual dos dois formatos o cabecalho e. None se nao for nenhum.

    O criterio e a presenca do fator de potencia: as duas bases tem `date` e
    `Usage_kWh`, e so a siderurgica tem `Lagging_Current_Power_Factor`.
    """
    nomes = {(coluna or "").strip() for coluna in (colunas or [])}
    if not {COLUNA_DATA, COLUNA_CONSUMO}.issubset(nomes):
        return None
    return FORMATO_SIDERURGICA if COLUNA_FATOR in nomes else FORMATO_SETOR


def converter_data(bruto: str, formato: str) -> datetime | None:
    """Le a data no formato daquela base. None se nao casar com nenhum."""
    texto = (bruto or "").strip()
    for molde in FORMATOS_DE_DATA[formato]:
        try:
            return datetime.strptime(texto, molde).replace(microsecond=0)
        except ValueError:
            continue
    return None


def converter_fator_do_percentual(bruto: str | None) -> Decimal | None:
    """Regra 6: o fator da siderurgica vem de 0 a 100 e e guardado de 0 a 1.

    Valor fora de 0 a 100 devolve None: a coluna tem CHECK de 0 a 1 e uma linha
    estranha nao pode derrubar a importacao inteira.
    """
    texto = (bruto or "").strip().replace(" ", "")
    if not texto:
        return None
    try:
        valor = Decimal(texto.replace(",", "."))
    except InvalidOperation:
        return None
    if valor < 0 or valor > 100:
        return None
    return (valor / DIVISOR_DO_PERCENTUAL).quantize(Decimal("0.001"))


def _ler_linhas(conteudo: str, formato: str, resultado: Resultado) -> list[dict]:
    """Converte as linhas do CSV, contando as que forem ignoradas e por que."""
    leitor = csv.DictReader(io.StringIO(conteudo))
    linhas = []

    for bruta in leitor:
        if len(linhas) + resultado.ignoradas >= MAXIMO_DE_LINHAS:
            resultado.erros.append(
                f"O arquivo tem mais de {MAXIMO_DE_LINHAS:,} linhas. "
                "Importe um trecho menor (um ano de um medidor são 35.040 linhas.)"
                .replace(",", ".")
            )
            break

        data_hora = converter_data(bruta.get(COLUNA_DATA, ""), formato)
        if data_hora is None:
            resultado.ignorar("data e hora inválidas")
            continue

        consumo, erro = converter_consumo(bruta.get(COLUNA_CONSUMO, ""))
        if erro:
            resultado.ignorar("consumo inválido")
            continue

        fator = (
            converter_fator_do_percentual(bruta.get(COLUNA_FATOR))
            if formato == FORMATO_SIDERURGICA
            else None
        )
        linhas.append({"data_hora": data_hora, "consumo_kwh": consumo, "fator_potencia": fator})

    # A siderurgica NAO esta em ordem cronologica (secao 2.2 de
    # docs/bases-de-dados.md): a linha das 00:00 vem no fim de cada dia. Ordenar
    # e obrigatorio antes de montar qualquer lag — sem isso a previsao da
    # primeira leitura de cada dia sairia com os lags trocados.
    linhas.sort(key=lambda linha: linha["data_hora"])
    return linhas


def _sem_duplicadas(linhas: list[dict], id_medidor: int, resultado: Resultado) -> list[dict]:
    """Regra 3: tira as repetidas, dentro do arquivo e contra o que ja esta no banco."""
    if not linhas:
        return []

    ja_no_banco = leitura_repository.data_horas_existentes(
        id_medidor, linhas[0]["data_hora"], linhas[-1]["data_hora"]
    )
    vistas = set()
    limpas = []

    for linha in linhas:
        quando = linha["data_hora"]
        if quando in ja_no_banco:
            resultado.ignorar("já existe uma leitura nesta data e hora")
        elif quando in vistas:
            resultado.ignorar("repetida dentro do próprio arquivo")
        else:
            vistas.add(quando)
            limpas.append(linha)

    return limpas


def _prever(medidor, linhas: list[dict]) -> list[Decimal | None]:
    """Monta os lags de cada linha e preve todas de uma vez.

    Os lags saem da propria serie: as do arquivo, e para as primeiras linhas as
    que ja estao no banco antes do inicio do arquivo. E por isso que uma segunda
    importacao, continuando de onde a primeira parou, ja comeca com previsao.
    """
    anteriores = leitura_repository.anteriores_a(
        medidor.id, linhas[0]["data_hora"], previsao_service.LEITURAS_NECESSARIAS
    )
    # Do mais recente para o mais antigo, que e a ordem dos lags.
    serie = [float(leitura.consumo_kwh) for leitura in anteriores]

    periodos = []
    for linha in linhas:
        periodos.append((linha["data_hora"], list(serie)))
        serie.insert(0, float(linha["consumo_kwh"]))
        del serie[previsao_service.LEITURAS_NECESSARIAS:]

    return previsao_service.prever_em_lote(medidor, periodos)


def importar(medidor, conteudo: str) -> Resultado:
    """Importa o CSV para o medidor. Devolve o resumo que a tela mostra."""
    resultado = Resultado()

    if medidor is None:
        resultado.erros.append("Escolha o medidor que vai receber as leituras.")
        return resultado
    if not medidor.ativo:
        resultado.erros.append(
            f"O medidor “{medidor.codigo}” está desativado e não aceita leitura nova."
        )
        return resultado

    cabecalho = next(csv.reader(io.StringIO(conteudo)), None)
    resultado.formato = detectar_formato(cabecalho)
    if resultado.formato is None:
        resultado.erros.append(
            "Não reconheci o formato do arquivo. O CSV precisa ter as colunas "
            "“date” e “Usage_kWh” — é o formato da base da siderúrgica e o dos "
            "arquivos de data/setores/."
        )
        return resultado

    linhas = _sem_duplicadas(_ler_linhas(conteudo, resultado.formato, resultado), medidor.id,
                             resultado)
    if not linhas:
        # So avisa em vermelho quando nao ha nada a explicar — arquivo vazio ou
        # so com o cabecalho. Quando ha motivos, quem explica e o resumo da
        # tela, linha a linha; repetir aqui so empilharia aviso.
        if not resultado.erros and not resultado.motivos:
            resultado.erros.append(
                "O arquivo não tem nenhuma linha de leitura além do cabeçalho."
            )
        return resultado

    previsoes = _prever(medidor, linhas)
    leituras = [
        Leitura(
            id_medidor=medidor.id,
            data_hora=linha["data_hora"],
            consumo_kwh=linha["consumo_kwh"],
            fator_potencia=linha["fator_potencia"],
            consumo_previsto_kwh=previsto,
        )
        for linha, previsto in zip(linhas, previsoes)
    ]
    leitura_repository.salvar_varias(leituras)

    # Criterio da #27: a importacao tambem abre alertas. Como as leituras ja
    # estao gravadas e com id, o medidor precisa estar ligado a cada uma para o
    # AlertaService chegar ao setor e ao limite.
    for leitura in leituras:
        leitura.medidor = medidor
    alertas = alerta_service.abrir_para_varias(leituras)

    resultado.importadas = len(leituras)
    resultado.com_previsao = sum(1 for previsto in previsoes if previsto is not None)
    resultado.alertas = len(alertas)
    resultado.primeira = linhas[0]["data_hora"]
    resultado.ultima = linhas[-1]["data_hora"]
    return resultado
