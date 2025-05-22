FROM python:3.11-slim

# Installa il Docker CLI
RUN apt-get update && \
    apt-get install -y docker.io && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Assicurati che users.json esista, altrimenti crealo
RUN if [ ! -f /app/users.json ]; then echo "{}" > /app/users.json; fi

VOLUME ["/app/users.json"]

CMD ["python", "bot.py"]
