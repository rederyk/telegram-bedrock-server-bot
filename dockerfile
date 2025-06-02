FROM python:3.11-slim

# Installa il Docker CLI, i tool di build necessari (gcc, ecc.) e le librerie di sviluppo per leveldb
RUN apt-get update && \
    apt-get install -y docker.io build-essential libleveldb-dev zlib1g-dev wget openjdk-17-jre && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# Copy all project files
COPY . .

RUN wget -O importBuild/lite2Edit/Lite2Edit.jar https://github.com/GoldenDelicios/Lite2Edit/releases/download/v1.2.1/Lite2Edit.jar

RUN mkdir -p botData && if [ ! -f "botData/users.json" ]; then mv example.users.json botData/users.json; fi

# Setup venv for schem_to_mc_amulet
WORKDIR /app/importBuild/schem_to_mc_amulet
RUN if [ ! -d "venv" ]; then \
    python -m venv venv && \
    venv/bin/pip install --no-cache-dir -r requirements.txt; \
fi

# Setup venv for Structura
WORKDIR /app/importBuild/structura_env
RUN if [ ! -d "venv" ]; then \
    python -m venv venv && \
    venv/bin/pip install --no-cache-dir -r requirementsCLI.txt; \
fi

# Check if Structura is already cloned, if not, clone it
RUN if [ ! -d "Structura" ]; then git clone https://github.com/RavinMaddHatter/Structura.git; fi

# Return to the main app directory
WORKDIR /app

# Dichiara il volume
VOLUME ["/app"]

CMD ["python", "bot.py"]
