# GestEnergia — imagem da aplicacao (Python 3.11 + Flask)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Sao_Paulo

WORKDIR /app

# cliente mysql para rodar o banco.sql e inspecionar o banco de dentro do container
RUN apt-get update \
    && apt-get install -y --no-install-recommends default-mysql-client \
    && rm -rf /var/lib/apt/lists/*

# dependencias primeiro, para aproveitar o cache do Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["flask", "--app", "app", "run", "--host", "0.0.0.0", "--port", "5000", "--debug"]
