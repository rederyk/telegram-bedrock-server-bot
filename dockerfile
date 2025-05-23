FROM python:3.11-slim

# Installa il Docker CLI, i tool di build necessari (gcc, ecc.) e le librerie di sviluppo per leveldb
RUN apt-get update && \
    apt-get install -y docker.io build-essential libleveldb-dev zlib1g-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files
COPY . .

# Setup venv for schem_to_mc_amulet
WORKDIR /app/importBuild/schem_to_mc_amulet
RUN rm -rf venv && \
    python -m venv venv && \
    venv/bin/pip install --no-cache-dir -r requirements.txt

# Setup venv for Structura
WORKDIR /app/importBuild/structura_env
RUN rm -rf venv && \
    python -m venv venv && \
    venv/bin/pip install --no-cache-dir -r requirementsCLI.txt

# Check if Structura is already cloned, if not, clone it
RUN if [ ! -d "Structura" ]; then git clone https://github.com/RavinMaddHatter/Structura.git; fi

# Return to the main app directory
WORKDIR /app

# Dichiara il volume per il file (non per la directory)
VOLUME ["/app"]

CMD ["python", "bot.py"]
