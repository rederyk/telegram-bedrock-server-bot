# Telegram Bedrock Server Admin Bot

Un bot Telegram avanzato per amministrare server **Minecraft Bedrock Edition** tramite Docker. Offre un'interfaccia completa per gestire il server, interagire con i giocatori e manipolare file di struttura direttamente da Telegram.

---

## ✨ Funzionalità

### 🔐 Autenticazione e Sicurezza
- **Login sicuro** con password configurabile. Diversi livelli di accesso sono disponibili.
- **Gestione utenti** con associazione username Minecraft
- **Logout** per terminare la sessione

I livelli di autenticazione sono definiti nel file `config.py`. Quando un utente esegue il login con una password specifica, viene assegnato un livello di autorizzazione corrispondente. Questo livello determina quali comandi può utilizzare.

È possibile creare nuovi livelli di autorizzazione o modificare quelli esistenti direttamente nel file `config.py`, consentendo un controllo granulare sull'accesso ai comandi.

### 🎮 Gestione Server
- **Controllo container Docker**: Avvio, arresto e riavvio del server
- **Monitoraggio log**: Visualizzazione log in tempo reale
- **Esecuzione comandi**: Invio diretto di comandi alla console server
- **Avvio Server MC** (`/startserver`): Avvia il server Minecraft
- **Ferma Server MC** (`/stopserver`): Ferma il server Minecraft
- **Riavvia Server MC** (`/restartserver`): Riavvia il server Minecraft

### 🎒 Funzioni Interattive
- **Menu azioni rapide** (`/menu`): Interface a pulsanti per azioni comuni
- **Gestione inventario** (`/give`): Distribuzione oggetti con ricerca inline
- **Teletrasporto** (`/tp`): Teleport a giocatori, coordinate o posizioni salvate
- **Controllo meteo** (`/weather`): Modifica condizioni atmosferiche
- **Salvataggio posizioni** (`/saveloc`): Memorizza località per accesso rapido
- **Modifica utente/posizioni** (`/edituser`): Modifica utenti e posizioni salvate

### 💾 Backup e Manutenzione
- **Backup mondo** (`/backup_world`): Creazione backup compressi
- **Gestione backup** (`/list_backups`): Lista, download e ripristino backup esistenti
- **Reset flag creativo** (`/imnotcreative`): Ragigungi i tuoi obiettivi

### 📦 Resource Pack
- **Installazione automatica**: Tutti i file `.zip`/`.mcpack` inviati vengono automaticamente installati
- **Gestione pack attivi**: Modifica ordine priorità e rimozione pack installati
- **Aggiornamento database item**: Refresh lista oggetti Minecraft per comandi

### 🏗️ Strumenti per Strutture
- **Wizard automatico**: Caricamento file per elaborazione guidata
- **Divisione strutture** (`/split_structure`): Suddivisione file grandi
- **Conversione formati** (`/convert_structure`): Da `.schematic` a `.mcstructure`
- **Creazione resource pack** (`/create_resourcepack`): Generazione pack da strutture

### 🔍 Ricerca Avanzata
- **Ricerca inline**: Trova oggetti Minecraft digitando `@nomebot item`
- **Suggerimenti intelligenti**: Autocompletamento per comandi e oggetti

### 💻 Esecuzione Comandi Multipli
- **Comandi multipli**: Il comando `/cmd` supporta comandi Uno per riga
- **Commenti**: Righe che iniziano con `#` vengono ignorate

### 🌍 Gestione Posizioni Avanzata
- **Salvataggio illimitato**: Memorizza tutte le posizioni importanti
- **Accesso rapido**: Selezione da menu nel comando `/tp`
- **Gestione flessibile**: Modifica/elimina tramite `/edituser`

---

## ⚙️ Requisiti di Sistema

### Software Necessario
- **Docker** e **Docker Compose** (per l'esecuzione completa)
- **Container Minecraft Bedrock** (incluso nel `docker-compose.yml`)

### Credenziali Richieste
- **Token Bot Telegram** (ottenuto da BotFather)
- **Password di accesso** sicura per autenticazione utenti
- **Nome del mondo** Minecraft (se diverso da "Bedrock level")

---

## 🚀 Installazione e Configurazione

### 1. Clonazione Repository
```bash
git clone https://github.com/rederyk/telegram-bedrock-server-bot.git
cd telegram-bedrock-server-bot
```

### 2. Configurazione File
Copia i file di esempio e configurali:
```bash
cp example.env .env
cp example.users.json users.json
```

### 3. Configurazione Ambiente

#### Genera Password
per comodita  utilizza lo script `generate_passwords.sh` per generare password robuste per i diversi livelli di utente (CUSTOM, BASIC, PLAYER, MODERATOR, ADMIN).

```bash
./generate_passwords.sh
```

#### Modifica .env
Copia il file `example.env` in `.env`:

```bash
cp example.env .env
```

Modifica il file `.env` appena creato, inserendo il tuo token Telegram e il nome del tuo mondo Minecraft. Le password per i vari livelli di utente se non sono state generate tramite lo script `generate_passwords.sh`.

```env
# Configurazione Bot Telegram
TELEGRAM_TOKEN="IL_TUO_TOKEN_DA_BOTFATHER"
CUSTOM_PASSWORD="PASSWORD_CUSTOM"
BASIC_PASSWORD="PASSWORD_BASIC"
PLAYER_PASSWORD="PASSWORD_PLAYER"
MODERATOR_PASSWORD="PASSWORD_MODERATOR"
ADMIN_PASSWORD="PASSWORD_ADMIN"

# Configurazione Server Minecraft  
CONTAINER="bds"                   # Nome container (default dal compose)
WORLD_NAME="Bedrock level"           # Nome del tuo mondo (default Minecraft)

# Configurazioni Opzionali
BACKUPS_DIR_NAME="backups"           # Directory backup (default: backups)
LOG_LEVEL="INFO"                     # Livello logging (DEBUG|INFO|WARNING|ERROR|CRITICAL)
```

```bash
docker-compose up --build -d
```
---

## ⚠️ Avvertenze Importanti

### Sicurezza e Permessi
- Il bot richiede accesso a Docker tramite socket (`/var/run/docker.sock`)
- L'utente deve avere permessi Docker appropriati
- Le password del bot devono essere mantenute segrete

### Interruzioni Temporanee del Server
Questi comandi causano **brevi disconnessioni**:
- `/backup_world`: Per garantire integrità dei dati
- `/imnotcreative`: Per modificare file di mondo
- Riavvii del server per applicare resource pack

### 🐌 Limitazioni Tecniche
- **Download backup**: Limitato a file di dimensioni compatibili con Telegram API
- **Resource pack**: Modifiche diventano effettive dopo riavvio del server

---

## 📄 Licenza

Questo progetto è rilasciato sotto **Licenza MIT**. Vedi il file `LICENSE` per i dettagli completi.

---

## 🙏 Riconoscimenti

### Strumenti Utilizzati
Questo bot integra fantastici strumenti open source:
- **Container Server**: [`itzg/minecraft-bedrock-server`](https://github.com/itzg/docker-minecraft-bedrock-server)
- **[Amulet-Core](https://github.com/Amulet-Team/Amulet-Core)**: Manipolazione avanzata di file Minecraft (`.schematic`, `.mcstructure`)
- **[Structura](https://github.com/RyanLXXXVII/Structura)**: Creazione resource pack per visualizzazione modelli 3D in-game

*Realizzato con ❤️ per la community Minecraft Bedrock*
