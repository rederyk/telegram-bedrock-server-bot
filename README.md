# Telegram Bedrock Server Admin Bot

Un bot Telegram avanzato per amministrare server **Minecraft Bedrock Edition** tramite Docker. Offre un'interfaccia completa per gestire il server, interagire con i giocatori e manipolare file di struttura direttamente da Telegram.

---

## ✨ Funzionalità

### 🔐 Autenticazione e Sicurezza
- **Login sicuro** con password configurabile
- **Gestione utenti** con associazione username Minecraft
- **Logout** per terminare la sessione

### 🎮 Gestione Server
- **Controllo container Docker**: Avvio, arresto e riavvio del server
- **Monitoraggio log**: Visualizzazione log in tempo reale
- **Esecuzione comandi**: Invio diretto di comandi alla console server

### 🎒 Funzioni Interattive
- **Menu azioni rapide** (`/menu`): Interface a pulsanti per azioni comuni
- **Gestione inventario** (`/give`): Distribuzione oggetti con ricerca inline
- **Teletrasporto** (`/tp`): Teleport a giocatori, coordinate o posizioni salvate
- **Controllo meteo** (`/weather`): Modifica condizioni atmosferiche
- **Salvataggio posizioni** (`/saveloc`): Memorizza località per accesso rapido

### 💾 Backup e Manutenzione
- **Backup mondo** (`/backup_world`): Creazione backup compressi
- **Gestione backup** (`/list_backups`): Lista e download backup esistenti
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
Modifica il file `.env` appena creato:

```env
# Configurazione Bot Telegram
TELEGRAM_TOKEN="IL_TUO_TOKEN_DA_BOTFATHER"
BOT_PASSWORD="UNA_PASSWORD_SICURA_A_TUA_SCELTA"

# Configurazione Server Minecraft  
CONTAINER="bedrock"                   # Nome container (default dal compose)
WORLD_NAME="Bedrock level"           # Nome del tuo mondo (default Minecraft)

# Configurazioni Opzionali
BACKUPS_DIR_NAME="backups"           # Directory backup (default: backups)
LOG_LEVEL="INFO"                     # Livello logging (DEBUG|INFO|WARNING|ERROR|CRITICAL)
```

** 📝 Configurazione Obbligatoria:**
- **`TELEGRAM_TOKEN`**: Inserisci il token ottenuto da BotFather
- **`BOT_PASSWORD`**: Scegli una password sicura per l'accesso al bot
- **`WORLD_NAME`**: Se il tuo mondo non si chiama "Bedrock level", inserisci il nome corretto

### 4. Avvio Completo con Docker Compose
Il bot **richiede** il container del server Minecraft Bedrock per funzionare. Avvia entrambi i servizi:

```bash
docker-compose up --build -d
```
---

## ⚠️ Avvertenze Importanti

### Sicurezza e Permessi
- Il bot richiede accesso a Docker tramite socket (`/var/run/docker.sock`)
- L'utente deve avere permessi Docker appropriati
- La password del bot deve essere mantenuta segreta

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
