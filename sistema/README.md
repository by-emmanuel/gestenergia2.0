# GestEnergia — o sistema

[![CI](https://github.com/by-emmanuel/gestenergia2.0/actions/workflows/ci.yml/badge.svg)](https://github.com/by-emmanuel/gestenergia2.0/actions/workflows/ci.yml)

Sistema web para uma indústria acompanhar o consumo de energia de cada setor. São **4 setores, cada
um com a sua própria série real de consumo e o seu próprio modelo** de Machine Learning, que prevê o
consumo (kWh) dos próximos 15 minutos. O sistema gera alertas quando o consumo previsto passa do
limite daquele setor ou quando o fator de potência fica abaixo de 0,92 (mínimo da ANEEL).

> **Onde você está.** Esta pasta é o **sistema**. A análise de dados que gerou os quatro modelos de
> `ml/` está nas pastas `artigo/`, `notebook/` e `dataset/`, na raiz do repositório — veja o
> [README da raiz](../README.md). Os `.pkl` de `ml/` aqui e os de `modelos/` na raiz são os mesmos
> arquivos.

## Stack

| Camada | Tecnologia |
|---|---|
| Linguagem | Python 3.11 |
| Web | Flask + Jinja2 + Flask-Login |
| Banco | MySQL 8 via SQLAlchemy + PyMySQL |
| Modelo | pandas, scikit-learn 1.5.2, joblib |
| Gráficos | Chart.js servido localmente (`app/static/vendor/`) |
| Testes | pytest + pytest-flask |
| CI | GitHub Actions |

## Como rodar com Docker (recomendado)

Precisa apenas de **Docker** e **Docker Compose** instalados. Nada de Python nem MySQL na máquina.
Todos os comandos abaixo rodam **de dentro desta pasta** (`sistema/`).

```bash
# 1. copiar as variáveis de ambiente e preencher
cp .env.example .env

# 2. subir o banco (na primeira vez ele cria gestenergia e gestenergia_test
#    e executa o banco.sql automaticamente)
docker compose up -d db

# 3. subir o sistema
docker compose up app
# sistema em http://localhost:5000

# 4. conferir que a aplicação e o banco estão conversando
curl http://localhost:5000/saude
# {"aplicacao":"ok","banco":"ok","banco_detalhe":"8.0.xx","nome_do_banco":"gestenergia"}

# 5. carregar os dados da demonstração (sem isto o painel sobe vazio)
docker compose exec app flask --app app carregar-demonstracao --limpar

# 6. rodar os testes dentro do container
docker compose exec app pytest
docker compose exec app pytest tests/unit
```

A rota `/saude` responde **200** quando conecta no banco e **503** quando não conecta, dizendo o
motivo. É o jeito mais rápido de saber se o problema é na aplicação ou no MySQL.

Comandos úteis:

```bash
docker compose logs -f db          # acompanhar o banco
docker compose exec db mysql -uroot -proot gestenergia   # abrir o MySQL
docker compose down                # parar tudo (os dados do banco ficam salvos)
docker compose down -v             # apagar o volume e recriar o banco do zero
docker compose build --no-cache app   # reconstruir após mudar o requirements.txt
```

O MySQL do container fica exposto na porta **3307** da máquina (para não conflitar com um MySQL
já instalado). De fora do Docker, conecte em `localhost:3307`; de dentro, o host é `db:3306`.

**Porta 5000 ocupada?** No macOS o AirPlay Receiver (ControlCenter) escuta nela, e o container não
sobe: `bind: address already in use`. Em vez de desligar o AirPlay, ponha `PORTA_APP=5001` no `.env`
e use `http://localhost:5001` — dentro do container a porta é sempre 5000. Para descobrir quem está
ocupando: `lsof -nP -iTCP:5000 -sTCP:LISTEN`.

> Alterou o `banco.sql`? Ele só roda automaticamente na **primeira** criação do volume.
> Para reaplicar: `docker compose down -v && docker compose up -d db`.

## Como rodar sem Docker

> **Exige Python 3.10 ou mais novo — de preferência 3.11.** Isto foi **medido**, não suposto: com
> Python 3.9 o `pip install -r requirements.txt` **falha**, porque o `numpy 2.1.3` só existe a
> partir do 3.10 (a última versão para o 3.9 é a 2.0.2). Confira **antes** com
> `python3 --version`.
>
> Se a máquina tiver uma versão antiga e você não puder instalar outra, **use o caminho do Docker**,
> que não depende do Python da máquina.

```bash
python3 --version                  # precisa ser 3.10+; o projeto usa 3.11

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # trocar MYSQL_HOST para localhost
mysql -u root -p < banco.sql

# Carrega os dados da apresentação: 4 semanas de cada setor, com as datas
# alinhadas (ver "Os dados da demonstração", abaixo). Sem isto o sistema sobe
# funcionando, mas com o banco vazio e o painel sem nada para desenhar.
flask --app app carregar-demonstracao --limpar

flask --app app run --debug
pytest
```

## Os dados da demonstração

A base da siderúrgica é de **2018** e as três da ElectricityLoadDiagrams são de **2014**. Com cada
setor no seu ano, o painel nunca mostraria os 4 no mesmo período.

O comando `carregar-demonstracao` resolve isso deslocando as datas dos três setores novos em
**+1.463 dias (209 semanas)**, até caírem no mesmo período da siderúrgica. O deslocamento é um
**múltiplo de 7 dias** de propósito: `dia_semana` e `fim_de_semana` são atributos do modelo, e
deslocar os 1.461 dias exatos entre 01/01/2014 e 01/01/2018 jogaria uma quarta-feira para uma
segunda. O comando confere o dia da semana e falha se ele mudar.

> **Limitação a declarar na apresentação:** o deslocamento acontece **só nos dados da
> demonstração**, em memória, na hora de carregar o banco. Os CSVs de `data/setores/` ficam intactos
> com as datas originais, e é neles que os modelos de `ml/` foram treinados. Os três clientes também
> são **anônimos e de Portugal** — os nomes Administrativo, Utilidades e Manutenção são uma
> representação escolhida pelo grupo, não setores reais de uma mesma fábrica.

## As bases de dados

Duas bases do UCI Machine Learning Repository, ambas com medições a cada **15 minutos**:

| Setor | Base | Origem | Fator de potência |
|---|---|---|---|
| Produção | Steel Industry Energy Consumption | 1 siderúrgica, Coreia do Sul, 2018 | tem |
| Administrativo | ElectricityLoadDiagrams 2011–2014 | cliente anônimo, Portugal, 2014 | não tem |
| Utilidades | ElectricityLoadDiagrams 2011–2014 | cliente anônimo, Portugal, 2014 | não tem |
| Manutenção | ElectricityLoadDiagrams 2011–2014 | cliente anônimo, Portugal, 2014 | não tem |

Os três clientes da ElectricityLoadDiagrams foram escolhidos por K-means, para representar perfis de
consumo diferentes (horário comercial, 24 horas e um terceiro perfil). **Eles são clientes anônimos
de Portugal: os nomes Administrativo, Utilidades e Manutenção são uma representação escolhida pelo
grupo, não setores reais de uma mesma fábrica.**

O que está versionado aqui é o resultado do pré-processamento: um CSV por setor em `data/setores/`,
com as colunas `date` e `Usage_kWh`, mais a base da siderúrgica em `data/bruto/`. Todo o caminho que
produziu esses arquivos — e os números por trás deles — está na análise, na raiz do repositório.

### Download das bases originais

A ElectricityLoadDiagrams tem cerca de **678 MB** e por isso **não está neste repositório** (o limite
do GitHub é 100 MB por arquivo). Baixe direto da UCI:

- **Steel Industry Energy Consumption** (setor Produção) — página:
  <https://archive.ics.uci.edu/dataset/851> · download direto:
  <https://archive.ics.uci.edu/static/public/851/steel+industry+energy+consumption.zip>
  O ZIP traz `Steel_industry_data.csv` (35.040 instâncias). Fica em `data/bruto/`.
- **ElectricityLoadDiagrams 2011–2014** (setores Administrativo, Utilidades e Manutenção) — página:
  <https://archive.ics.uci.edu/dataset/321/electricityloaddiagrams20112014> · download direto:
  <https://archive.ics.uci.edu/static/public/321/electricityloaddiagrams20112014.zip>
  O ZIP traz `LD2011_2014.txt` (~678 MB descompactado, `sep=";"` e `decimal=","`, 370 colunas
  `MT_001`..`MT_370`). **Nunca baixar para dentro do repositório.**

> Citação: Trindade, A. (2015). ElectricityLoadDiagrams20112014 [Dataset]. UCI Machine Learning
> Repository. <https://doi.org/10.24432/C58C86> — Licença CC BY 4.0.
> Sathishkumar, V. E.; Shin, C.; Cho, Y. (2021). Steel Industry Energy Consumption [Dataset]. UCI
> Machine Learning Repository. <https://doi.org/10.24432/C52G8C> — Licença CC BY 4.0.

## Estrutura

```text
sistema/
├── app/                    # aplicação Flask
│   ├── __init__.py         # create_app()
│   ├── config.py           # lê as variáveis do .env
│   ├── banco.py            # motor e sessão do SQLAlchemy
│   ├── models.py           # Setor, Medidor, Leitura, Alerta, Usuario
│   ├── cli.py              # comando carregar-demonstracao
│   ├── repositories/       # todo o acesso ao banco
│   ├── services/           # regras de negócio
│   ├── routes/             # blueprints
│   ├── templates/          # telas HTML
│   └── static/vendor/      # Chart.js local (a máquina do laboratório pode estar sem internet)
├── ml/                     # os 4 modelos, um por setor
├── notebooks/              # os scripts que prepararam os dados e treinaram os modelos
├── data/
│   ├── bruto/              # base da siderúrgica
│   ├── processado/         # CSV pré-processado e as métricas
│   └── setores/            # um CSV por setor: date, Usage_kWh
├── tests/                  # unit, integration, system
├── docker/mysql/init/      # criação dos dois bancos
├── docker-compose.yml      # banco + sistema
├── Dockerfile
└── banco.sql               # tabelas + dados de exemplo
```

A arquitetura tem uma regra que vale para todo o código: **rota → service → repository**. Rotas não
acessam o banco direto, e regra de negócio não mora em template nem em rota, só em service.

## Regras de negócio

1. Fator de potência mínimo **0,92** — abaixo gera `FATOR_POTENCIA_BAIXO` (exatamente 0,92 não gera).
   Leitura sem fator de potência (`NULL`) não gera alerta e não dá erro: só o setor Produção tem
   esse dado.
2. Consumo previsto **maior** que o limite do setor gera `CONSUMO_ACIMA_LIMITE` (igual não gera).
3. Um medidor não pode ter duas leituras com a mesma `data_hora` — chave única no banco **e**
   validação no serviço.
4. A previsão precisa de **4 leituras anteriores** do mesmo medidor; com menos, devolve `None` e a
   tela mostra "sem previsão ainda".
5. A previsão nunca é negativa (`max(0.0, valor)`).
6. O fator de potência vem em percentual na base (ex.: 73,21) e é guardado de 0 a 1 (0,7321).
7. `OPERADOR` registra e importa leituras; `GESTOR` faz tudo, inclusive configurar limites e
   resolver alertas.
8. O registro de leitura com previsão responde em menos de **500 ms** — por isso os modelos são
   carregados uma única vez, na subida da aplicação.
9. **Um modelo por setor**, apontado por `setores.arquivo_modelo`. Setor sem modelo, ou com o
   arquivo ausente, devolve `None` sem derrubar a tela.
10. O limite de cada setor é o **percentil 99** do consumo daquele setor no período de treino
    (cerca de 7 alertas por semana por setor).

## Testes e CI

```bash
pytest                 # todos
pytest tests/unit      # regras puras, sem banco
pytest tests/integration   # repositórios contra o MySQL de teste (gestenergia_test)
pytest tests/system    # fluxos completos: login → cadastro → leitura → alerta → resolver
pytest -k alerta       # filtra pelo nome
```

A suíte tem **520 testes** (unitários, de integração e de sistema). Ela foi executada a partir
desta pasta, contra um MySQL 8 de verdade: **520 passaram, em 55 s**.

Casos de borda cobertos de propósito: fator 0,91 / 0,92 / 0,93; consumo igual e acima do limite;
leitura duplicada; menos de 4 leituras; setor sem arquivo de modelo; `.pkl` corrompido.

O CI roda a cada push e a cada pull request na `main`, e faz exatamente o que se faz na máquina:
sobe o MySQL 8, cria os dois bancos, **aplica o `banco.sql`** e roda a suíte. O arquivo fica na
**raiz do repositório** — [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) —, porque o
GitHub só lê workflows de lá; todos os passos de shell dele rodam com `working-directory: sistema`.

## Autoria

Projeto A3 da Universidade Potiguar, desenvolvido por **Lucas Azevedo Costa**.
