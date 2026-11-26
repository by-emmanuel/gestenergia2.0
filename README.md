# GestEnergia — Análise de Dados e Big Data

Trabalho da A3 de **Análise de Dados e Big Data** (Profª Me. Edjane Azevêdo — Universidade
Potiguar). O repositório reúne, num só lugar, **a análise completa**: o artigo, o notebook que
produz todos os números, as bases usadas e os quatro modelos treinados.

| | |
|---|---|
| Entrega e apresentação | **26/11/2026** |
| Campo no Ulife | `ENTREGA DA A3 - ARQUIVOS` |
| Enunciado original | [`enunciado/A3-analise-de-dados-e-big-data.pdf`](enunciado/A3-analise-de-dados-e-big-data.pdf) |
| Artigo pronto | [`artigo/artigo.pdf`](artigo/artigo.pdf) — 12 páginas, template SBC |
| Notebook | [`notebook/GestEnergia_A3_Analise_de_Dados_e_Big_Data.ipynb`](notebook/GestEnergia_A3_Analise_de_Dados_e_Big_Data.ipynb) — 49 células, roda no Colab |

## Em uma frase

A partir de **duas bases públicas e reais** de consumo elétrico medido a cada 15 minutos, o trabalho
caracteriza quatro séries de setores industriais, processa um arquivo de **678 MB em fluxo**, trata
os problemas encontrados nos dados e treina **um modelo por setor** para prever o consumo dos
próximos 15 minutos — comparando cada modelo com uma linha de base ingênua para medir **quanto o
aprendizado de máquina realmente acrescenta**. A resposta honesta é: menos do que o R² sugere.

---

## 1. Como ler este repositório

```text
.
├── artigo/        o artigo em LaTeX (fonte, PDF, template SBC e as 6 figuras)
├── notebook/      o programa da análise, de ponta a ponta, em Jupyter/Colab
├── dataset/       as bases usadas e as saídas medidas da análise (JSON)
├── modelos/       os 4 modelos treinados, um por setor (.pkl)
├── enunciado/     o PDF do enunciado da A3
├── requirements.txt   as versões exatas em que tudo foi medido
└── sistema/       o sistema web que usa esses 4 modelos (Flask + MySQL)
```

As cinco primeiras pastas são **a análise**. A pasta `sistema/` é **a aplicação** que consome os
modelos treinados aqui — ela tem o [seu próprio README](sistema/README.md), com as instruções de
instalação e execução.

Se você tem **cinco minutos**, leia o artigo. Se tem **vinte**, abra o notebook no Colab e rode
tudo: ele reproduz cada número do artigo, na ordem em que o enunciado pede as etapas.

---

## 2. A pergunta

Uma indústria quer saber, a cada 15 minutos, **quanto cada setor vai consumir nos próximos 15
minutos** — para antecipar picos antes que eles aconteçam, em vez de descobrir no fim do mês pela
fatura. Isso levanta três perguntas de dados, e são elas que o trabalho responde:

1. **Como são, de fato, essas séries?** Quantas instâncias, quantos atributos, quais problemas.
2. **Como processar uma base que não cabe na memória?** A base da ElectricityLoadDiagrams tem
   678 MB e 370 clientes; é a parte "Big Data" do trabalho.
3. **Previsão a 15 minutos vale a pena?** Ou repetir o valor anterior já resolve? Essa é a
   pergunta que a maioria dos trabalhos não faz, e aqui ela é medida.

---

## 3. As bases

Duas bases públicas do **UCI Machine Learning Repository**, as duas com medição a cada 15 minutos,
o que permite tratar os quatro setores com exatamente o mesmo código.

| Setor | Base | Origem | Linhas | Fator de potência |
|---|---|---|---|---|
| Produção | Steel Industry Energy Consumption ([UCI 851](https://archive.ics.uci.edu/dataset/851)) | siderúrgica DAEWOO, Coreia do Sul, 2018 | 35.040 | **tem** |
| Administrativo | ElectricityLoadDiagrams 2011–2014 ([UCI 321](https://archive.ics.uci.edu/dataset/321)) | cliente `MT_013`, Portugal, 2014 | 35.040 | não |
| Utilidades | ElectricityLoadDiagrams 2011–2014 ([UCI 321](https://archive.ics.uci.edu/dataset/321)) | cliente `MT_060`, Portugal, 2014 | 35.040 | não |
| Manutenção | ElectricityLoadDiagrams 2011–2014 ([UCI 321](https://archive.ics.uci.edu/dataset/321)) | cliente `MT_286`, Portugal, 2014 | 35.040 | não |

**140.160 instâncias** no total. Nenhum atributo é multivalorado — isso foi testado, não suposto
(seção 2 do notebook procura separadores dentro de cada célula).

### Aviso de honestidade

Os clientes da ElectricityLoadDiagrams são **anônimos e portugueses**. Os nomes *Administrativo*,
*Utilidades* e *Manutenção* são uma **representação escolhida pelo grupo** para três perfis de
consumo distintos, encontrados por K-means; **não** são setores reais de uma mesma fábrica. Só a
Produção vem de uma planta industrial identificada, e é a única com fator de potência medido.
Isso está dito no artigo e deve ser repetido na apresentação.

### Licenças

Ambas são **CC BY 4.0** e exigem citação:

- Trindade, A. (2015). *ElectricityLoadDiagrams20112014* [Dataset]. UCI Machine Learning
  Repository. <https://doi.org/10.24432/C58C86>
- Sathishkumar, V. E.; Shin, C.; Cho, Y. (2021). *Steel Industry Energy Consumption* [Dataset].
  UCI Machine Learning Repository. <https://doi.org/10.24432/C52G8C>

### O que está em `dataset/`

| Arquivo | O que é |
|---|---|
| `Steel_industry_data.csv` | base da UCI 851, original e completa (11 colunas) |
| `administrativo.csv`, `utilidades.csv`, `manutencao.csv` | as três séries extraídas da UCI 321, já em kWh e com o horário de verão corrigido (`date`, `Usage_kWh`) |
| `perfil_clientes_2014.csv` | média e % de zeros dos **370** clientes, medidos em fluxo no arquivo de 678 MB |
| `setores_kmeans.json` | os 3 grupos do K-means, os clientes escolhidos e o limite de cada setor |
| `preprocessamento.json` | linhas, corte treino/teste e média no teste de cada setor |
| `metricas_modelos.json` | os **5 algoritmos × 4 setores**, com MAE, MAE%, RMSE, R², tempo e tamanho |
| `modelos_finais.json` | o modelo escolhido por setor e a importância dos 9 atributos |

> O arquivo original `LD2011_2014.txt` (678 MB) **não** está aqui: é público e passa do limite de
> 100 MB do GitHub. Baixe de <https://archive.ics.uci.edu/dataset/321> se quiser rodar a seção 3
> do notebook com o arquivo de verdade.

---

## 4. O caminho da análise

As cinco etapas que o enunciado cobra, e onde cada uma está no notebook:

| Etapa | Seção | O que foi feito |
|---|---|---|
| **Seleção** | 2 | caracterização medida das duas bases: instâncias, atributos, tipos, faltantes e o teste de multivalorados |
| **Big Data** | 3 | leitura do arquivo de 678 MB em partes (`chunksize`), com **medição de memória** |
| **Pré-processamento** | 4 e 5 | cinco tratamentos + o K-means que escolhe os 3 clientes |
| **Visualização** | 6 | perfil horário, distribuição, uma semana típica e autocorrelação |
| **Análise** | 7 a 11 | engenharia de atributos, 5 algoritmos × 4 setores, resultados e modelos salvos |

### A parte de Big Data, em números

O arquivo de 678 MB tem 371 colunas (a data e os 370 clientes) e 140.256 linhas. Lido de uma vez, o pico de memória chega a
**1.037 MB**; lido em partes de 20 mil linhas, cai para **256 MB** — sem perder nenhum dado, porque
o que interessa (média e % de zeros por cliente) é acumulado parte a parte. A figura 1 do artigo
mostra a curva de memória por tamanho de parte (216 / 256 / 499 / 1.037 MB).

Depois dessa varredura, só as **3 colunas escolhidas** são lidas de novo, com `usecols`.

### Os cinco tratamentos do pré-processamento

1. **kW médio → kWh**: a base portuguesa mede kW médio do período de 15 min; dividir por 4.
2. **Clientes incompletos fora**: quem entrou depois de 2011 tem zeros até começar a medir —
   **30 dos 370** foram descartados por terem mais de 1% de zeros em 2014.
3. **Horário de verão de março** (30/03/2014): a hora que não existiu deixa 480 células zeradas
   entre 1h e 2h; 760 períodos interpolados.
4. **Horário de verão de outubro** (26/10/2014): os valores entre 1h e 2h somam duas horas,
   divididos por 2 — 760 períodos corrigidos. Nenhum `NaN` sobrou.
5. **Escolha dos 3 clientes por K-means** (3 grupos; cada candidato é um vetor de 48 posições —
   a média por hora em dias úteis (24) e em fins de semana (24), normalizada), para garantir perfis
   de consumo **diferentes entre si**, e não três cópias do mesmo.

### Os atributos do modelo

Nove, iguais nos quatro setores: `hora`, `minuto`, `dia_semana`, `mes`, `fim_de_semana` e os quatro
atrasos `lag_1` a `lag_4` (consumo de 15, 30, 45 e 60 minutos antes).

Ficaram **deliberadamente de fora** o CO₂, as potências reativas e o fator de potência **do mesmo
período**: eles vazam a resposta (são medidos junto com o alvo) e só existem em um dos setores.

Separação treino/teste **por tempo**, nunca embaralhada: 10 primeiros meses para treino (29.180
períodos), 2 últimos para teste (5.856). Embaralhar colocaria o futuro no treino.

---

## 5. Resultados

### O modelo escolhido, por setor

**Gradient Boosting nos quatro setores**, escolhido por ser o melhor ou empatar com o melhor, com
0,19 MB por modelo e 0,22 ms por previsão (contra 230 MB e 12,3 ms do Random Forest).

| Setor | MAE (kWh) | MAE% | RMSE | R² | Média no teste (kWh) |
|---|---|---|---|---|---|
| Produção | 5,031 | 20,23% | 9,519 | 0,907 | 24,87 |
| Administrativo | 1,633 | 8,61% | 2,154 | 0,971 | 18,97 |
| Utilidades | 0,495 | 6,92% | 0,652 | 0,875 | 7,15 |
| Manutenção | 1,214 | 4,02% | 1,790 | 0,964 | 30,17 |

O **MAE% existe porque os setores têm escalas diferentes**: um erro de 5 kWh é grande num setor que
consome 7 kWh de média e pequeno num que consome 30. Comparar MAE em kWh entre setores não diz nada;
o MAE% diz.

### O resultado mais importante: o ganho sobre a linha de base

A linha de base **ingênua** prevê que o próximo período repete o anterior. Sem ela, um R² de 0,97
pareceria excelente:

| Setor | Melhor algoritmo | MAE% | Ingênuo | Ganho |
|---|---|---|---|---|
| Produção | Random Forest | 18,39% | 20,89% | 12,0% |
| Administrativo | Gradient Boosting | 8,61% | 9,45% | 8,9% |
| Utilidades | Gradient Boosting | 6,92% | 6,98% | **0,9%** |
| Manutenção | Random Forest | 3,67% | 4,29% | 14,5% |

Nas Utilidades — a série quase plana, 24 horas por dia — o aprendizado de máquina **praticamente
empata** com repetir o valor anterior: numa série sem padrão além da própria inércia, não há o que
aprender. O ganho é real nos outros setores, mas modesto.

A explicação aparece na importância dos atributos: o `lag_1` responde por **94,3% a 98,4%** do
modelo (Produção 94,3%, Utilidades 96,3%, Manutenção 96,6%, Administrativo 98,4%). A hora do dia
vem em segundo lugar, com no máximo 2,6%. Ou seja: o modelo é, essencialmente, o valor anterior
ajustado — e é por isso que não consegue superar por muito quem usa só o valor anterior.

### O achado que não estava na pergunta

Na siderúrgica, o **fator de potência fica abaixo do mínimo de 0,92 da ANEEL em 60,4% dos 35.040
períodos** do ano — e não só sob carga baixa: no decil de maior consumo ainda são 53,4%. É uma
planta que, no Brasil, pagaria multa. A figura 6 do artigo mostra isso.

---

## 6. Os 4 modelos treinados

Cada arquivo de `modelos/` é um **pipeline completo** do scikit-learn (pré-processamento + modelo),
salvo com `joblib`, treinado só no período de treino.

```python
import joblib
import pandas as pd

modelo = joblib.load("modelos/modelo_consumo_producao.pkl")

# a ordem das colunas tem de ser exatamente esta
atributos = ["hora", "minuto", "dia_semana", "mes", "fim_de_semana",
             "lag_1", "lag_2", "lag_3", "lag_4"]

x = pd.DataFrame([[14, 30, 2, 6, 0, 22.4, 21.9, 23.1, 22.8]], columns=atributos)
print(max(0.0, float(modelo.predict(x)[0])))   # kWh previstos para os próximos 15 min
```

Dois cuidados: **scikit-learn 1.5.2** (em outra versão o `.pkl` pode não abrir) e previsão
**nunca negativa** — daí o `max(0.0, ...)`.

---

## 7. Como reproduzir

### O notebook, no Colab (o caminho mais simples)

1. `Arquivo → Fazer upload de notebook` e envie o `.ipynb` de `notebook/`.
2. `Ambiente de execução → Executar tudo`.
3. A célula 1.2 procura os dados e, se não achar, abre o seletor de upload: envie os CSVs de
   `dataset/`.

A seção 3 (o arquivo de 678 MB) é **opcional**: sem o `LD2011_2014.txt` o notebook imprime os
valores já medidos e segue em frente. Sem ela, a execução leva cerca de 2 minutos.

### Localmente

```bash
pip install -r requirements.txt

# roda as 27 células de código em sequência e para no primeiro erro
python notebook/executa_notebook.py notebook/GestEnergia_A3_Analise_de_Dados_e_Big_Data.ipynb

# regera as 6 figuras do artigo, no tamanho exato de impressão
python artigo/figuras_artigo.py artigo/figuras
```

Rode da **raiz do repositório**: é daí que os scripts encontram `dataset/`.

**Verificação feita:** as 27 células de código foram executadas de ponta a ponta, com o arquivo de
678 MB presente, sem nenhum erro, em Python 3.11.17 / pandas 2.2.3 / scikit-learn 1.5.2.

### O artigo em PDF

```bash
cd artigo && ./compilar.sh       # precisa de Docker; na 1ª vez baixa o TeX Live (~2 GB)
```

Ou no **Overleaf**, como o enunciado pede:

1. Abra o [template SBC](https://www.overleaf.com/latex/templates/sbc-conferences-template-updated-sbc-template-dot-sty-v2017/pyhttxftxjqn)
   e clique em **Open as Template**.
2. Substitua o `.tex` principal pelo conteúdo de `artigo/artigo.tex`.
3. Crie a pasta `figuras` e envie as **6 imagens** de `artigo/figuras/`.
4. Compile com **pdfLaTeX**.

> O `.tex` carrega `amsmath`, que o template SBC não traz. Sem ele a fórmula do MAE% quebra a
> compilação — já está no preâmbulo, só não remova.

### As figuras

| Arquivo | No artigo | Conteúdo |
|---|---|---|
| `fig3_memoria_chunksize.png` | Figura 1 | pico de memória × tamanho da parte lida, no arquivo de 678 MB |
| `fig1_perfil_por_hora.png` | Figura 2 | perfil médio por hora dos 4 setores, absoluto e normalizado |
| `fig4_mae_percentual.png` | Figura 3 | MAE% por setor e por algoritmo, com o ingênuo destacado |
| `fig5_real_x_previsto.png` | Figura 4 | consumo real e previsto em 3 dias do período de teste |
| `fig6_importancia.png` | Figura 5 | importância dos 9 atributos no modelo de cada setor |
| `fig7_fator_de_potencia.png` | Figura 6 | fator de potência da siderúrgica contra o mínimo de 0,92 |

Elas são desenhadas **no tamanho exato em que saem impressas** (6,3 pol de largura útil do template
SBC) e incluídas em escala 1:1. Aumentar a largura no `\includegraphics` sem regerá-las deixa tudo
borrado; diminuir deixa os rótulos ilegíveis. Para mudar de tamanho, ajuste o `figsize` em
`artigo/figuras_artigo.py` e rode o script de novo.

---

## 8. Antes de entregar

1. **Preencher os nomes.** Procure por `PREENCHER` em `artigo/artigo.tex` — autores (linha 48),
   curso, instituição e e-mails (linhas 53-54). O `artigo.pdf` que está aqui foi compilado com
   esses campos em branco.
2. **Gerar o PDF de novo**: `cd artigo && ./compilar.sh`.
3. **Subir no Ulife**: o `artigo.pdf`, os CSVs de `dataset/` e o `.ipynb`.

O artigo está em **12 páginas cheias**, no limite de 10 a 12 do enunciado: qualquer parágrafo a
mais empurra para 13. Se isso acontecer, o `.tex` tem um bloco marcado `CORTE OPCIONAL 2` (a
subseção *Limitações*) que libera cerca de meia página.

---

## 9. Limitações, ditas na cara

- **O ganho sobre o ingênuo é pequeno** (0,9% a 14,5%), e isso é apresentado como resultado, não
  escondido. Previsão a 15 minutos é dominada pela inércia da série.
- **Três dos quatro setores são uma representação**, não setores de uma fábrica real (seção 3).
- **Um ano por setor.** Não há como separar tendência de ciclo anual com uma única temporada.
- **O horizonte é de um passo** (15 minutos). Prever 1 hora ou 1 dia à frente é outro problema, e a
  vantagem sobre o ingênuo tende a crescer justamente aí — é o trabalho futuro natural.
- **Os quartis dos 340 clientes completos** são 73,1 / 140,1 / 356,0 kW. Se você encontrar
  62,8 / 125,7 / 306,0 em algum material mais antigo do grupo, esses são os quartis dos **370**
  clientes, com os incompletos incluídos; o artigo usa os corrigidos. A razão de 8.238× entre
  máximo e mínimo não muda, porque vem dos extremos.

---

## 10. O sistema que usa esses modelos

A análise não termina num relatório: os quatro modelos de `modelos/` são usados em produção por um
**sistema web** em Flask + MySQL, que está em [`sistema/`](sistema/). Ele registra as leituras de
cada medidor, prevê o consumo dos próximos 15 minutos a cada leitura nova e abre alertas quando a
previsão passa do limite do setor ou quando o fator de potência cai abaixo de 0,92.

Três coisas que a análise impõe ao sistema, e que explicam decisões do código:

- **Um modelo por setor.** Os quatro `.pkl` são carregados **uma única vez**, quando a aplicação
  sobe — carregar a cada leitura estouraria o limite de 500 ms por requisição.
- **Quatro leituras anteriores.** Como `lag_1` a `lag_4` são atributos do modelo, um medidor com
  menos de 4 leituras não tem previsão, e a tela diz isso em vez de inventar um número.
- **O limite de cada setor é o percentil 99** do consumo daquele setor no período de treino, nunca
  um valor único para todos: as escalas vão de 7 a 30 kWh de média.

Para subir o sistema, veja [`sistema/README.md`](sistema/README.md). O sistema é a entrega de
**outra disciplina** (Gestão e Qualidade de Software) — está aqui porque é o destino prático desta
análise, não como parte da A3 de Análise de Dados e Big Data.
