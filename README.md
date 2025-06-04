---
# Telegram Bedrock Server Admin Bot

Un bot Telegram avanzato per amministrare server **Minecraft Bedrock Edition** tramite Docker. Offre un'interfaccia completa per gestire il server, interagire con i giocatori, manipolare file di struttura e molto altro, direttamente da Telegram.

---

## 🚀 Guida Rapida: Installazione e Avvio

Mettere in funzione il bot è semplice. Segui questi passaggi:

1.  **Clona il Repository:**
    ```bash
    git clone [https://github.com/rederyk/telegram-bedrock-server-bot.git](https://github.com/rederyk/telegram-bedrock-server-bot.git)
    cd telegram-bedrock-server-bot
    ```

2.  **Configura i File Iniziali:**
    Copia i file di esempio:
    ```bash
    cp example.env .env
    ```
    
3.  **Modifica il File `.env`:**
    Apri il file `.env` e inserisci:
    * `TELEGRAM_TOKEN`: Il token del tuo bot Telegram (ottenuto da @BotFather).
    * `WORLD_NAME`: Il nome esatto del tuo mondo Minecraft (es. "Bedrock level").
    * **Passwords**: Se non hai usato lo script `generate_passwords.sh`, imposta manualmente le password per `CUSTOM_PASSWORD`, `BASIC_PASSWORD`, `PLAYER_PASSWORD`, `MODERATOR_PASSWORD`, `ADMIN_PASSWORD`.
    * `CONTAINER`: (Opzionale) Il nome del container Docker del server Bedrock, se diverso da "bds" (che è il default nel `docker-compose.yaml`).
    Esempio di `.env`:
    ```env
    # Configurazione Bot Telegram
    TELEGRAM_TOKEN="IL_TUO_TOKEN_DA_BOTFATHER"
    CUSTOM_PASSWORD="PASSWORD_CUSTOM_GENERATA"
    BASIC_PASSWORD="PASSWORD_BASIC_GENERATA"
    PLAYER_PASSWORD="PASSWORD_PLAYER_GENERATA"
    MODERATOR_PASSWORD="PASSWORD_MODERATOR_GENERATA"
    ADMIN_PASSWORD="PASSWORD_ADMIN_GENERATA"

    # Configurazione Server Minecraft
    CONTAINER="bds"                   # Nome container (default dal compose)
    WORLD_NAME="Bedrock level"        # Nome del tuo mondo

    # Configurazioni Opzionali
    BACKUPS_DIR_NAME="backups"        # Directory backup (default: backups)
    LOG_LEVEL="INFO"                  # Livello logging (DEBUG|INFO|WARNING|ERROR|CRITICAL)
    ```

4.  **Avvia i Container Docker:**
    ```bash
    docker-compose up --build -d
    ```
    Questo comando costruirà l'immagine del bot (se non esiste già) e avvierà sia il bot che il server Minecraft Bedrock (come definito nel file `docker-compose.yaml`).

5.  **Interagisci con il Bot su Telegram:**
    Cerca il tuo bot su Telegram e invia il comando `/login TUA_PASSWORD_ADMIN` (o la password per il livello di accesso desiderato) per iniziare.

---

## ✨ Funzionalità Principali

Questo bot offre una vasta gamma di funzionalità per semplificare l'amministrazione del tuo server Bedrock:

### 🔐 Autenticazione e Sicurezza
* **Login Sicuro**: Protezione tramite password con diversi livelli di accesso configurabili (CUSTOM, BASIC, PLAYER, MODERATOR, ADMIN).
* **Gestione Utenti**: Associazione degli utenti Telegram ai loro username Minecraft per comandi personalizzati.
* **Livelli di Autorizzazione**: Definiti nel file `config.py`, ogni livello ha permessi specifici che determinano quali comandi possono essere utilizzati.
* **Logout**: Per terminare la sessione corrente.

### 🎮 Gestione Server
* **Controllo Container Docker**: Avvia (`/startserver`), arresta (`/stopserver`) e riavvia (`/restartserver`) il container del server Minecraft.
* **Monitoraggio Log**: Visualizza gli ultimi log del server direttamente su Telegram (`/logs`).
* **Esecuzione Comandi**: Invia comandi direttamente alla console del server Minecraft (`/cmd`). Supporta comandi multipli (uno per riga) e commenti (righe che iniziano con `#`).

### 🎒 Funzioni Interattive e Giocatore
* **Menu Azioni Rapide (`/menu`)**: Un'interfaccia a pulsanti per accedere rapidamente alle azioni più comuni come `/give`, `/tp`, e `/weather`.
* **Gestione Inventario (`/give`)**: Distribuisci oggetti ai giocatori con una comoda ricerca inline (digitando `@nomebot item <nome_oggetto>`).
* **Teletrasporto (`/tp`)**: Teletrasporta te stesso o altri giocatori a coordinate specifiche, altri giocatori online o posizioni salvate.
* **Controllo Meteo (`/weather`)**: Cambia le condizioni atmosferiche del mondo (sereno, pioggia, temporale).
* **Gestione Posizioni Avanzata**: Salva (`/saveloc`) un numero illimitato di posizioni importanti nel mondo e accedi rapidamente ad esse tramite il menu `/tp`. Modifica o elimina posizioni e utenti con `/edituser`.

### 💾 Backup e Manutenzione
* **Backup Mondo (`/backup_world`)**: Crea backup compressi (.zip) del tuo mondo. Il server viene temporaneamente fermato per garantire l'integrità dei dati.
* **Gestione Backup (`/list_backups`)**: Elenca i backup esistenti, scaricali direttamente su Telegram o ripristina un backup specifico.
* **Reset Flag Creativo (`/imnotcreative`)**: Rimuove il flag "HasBeenLoadedInCreative" dal `level.dat` del mondo, utile per chi vuole mantenere gli achievement attivi. Richiede conferma e arresta/riavvia il server.

### 📦 Gestione Resource Pack
* **Installazione Semplificata**: Invia un file `.zip` o `.mcpack` al bot per installarlo.
* **Attivazione e Ordinamento (`/editresourcepacks`)**: Gestisci i resource pack attivi nel mondo, modifica il loro ordine di priorità o rimuovili.

### 🏗️ Strumenti Avanzati per Strutture
Il bot integra potenti strumenti per la gestione di file di strutture Minecraft:
* **Wizard Automatico per Strutture**: Caricando un file `.schematic`, `.schem` o `.mcstructure`, il bot avvia un processo guidato che può includere:
    * **Divisione (`/split_structure`)**: Suddivide automaticamente strutture grandi in parti più piccole (file `.schematic`) se superano una soglia di blocchi.
    * **Conversione (`/convert_structure`)**: Converte file dal formato `.schematic` al formato `.mcstructure` per Bedrock.
    * **Creazione Resource Pack (`/create_resourcepack`)**: Genera un resource pack (file `.mcpack`) da uno o più file `.mcstructure` per visualizzare modelli 3D della struttura in gioco utilizzando lo strumento Structura.
* **Conversione Litematica**: Caricando un file `.litematic`, il bot lo convertirà automaticamente in un file `.schematic`.
* **Incollare Strutture (PasteHologram - WIP)**: Funzionalità sperimentale per incollare strutture nel mondo utilizzando un armor stand come riferimento. (Attualmente in fase di sviluppo attivo e potrebbe richiedere aggiustamenti).

---

## ⚙️ Requisiti di Sistema

### Software Necessario
* **Docker** e **Docker Compose**: Essenziali per l'esecuzione del bot e del server Minecraft.

### Credenziali e Configurazione
* **Token del Bot Telegram**: Ottenibile da @BotFather su Telegram.
* **Password di Accesso**: Definite nel file `.env` per i vari livelli di utente.
* **Nome del Mondo Minecraft**: Necessario per operazioni specifiche come backup e gestione dei resource pack.

---

## ⚠️ Avvertenze Importanti

### Sicurezza e Permessi
* **Accesso a Docker Socket**: Il bot necessita di accesso al socket Docker (`/var/run/docker.sock`) per gestire i container. Questo è configurato nel `docker-compose.yaml`. Assicurati che l'utente che esegue Docker abbia i permessi corretti.
* **Segretezza delle Password**: Mantieni le password definite nel file `.env` assolutamente segrete.

### Interruzioni Temporanee del Server
Alcuni comandi causano brevi interruzioni del server Minecraft per garantire l'integrità dei dati o per applicare modifiche:
* `/backup_world`
* `/imnotcreative`
* Applicazione di modifiche ai resource pack (richiede `/restartserver`)
* Operazioni di paste hologram (arresto, backup, paste, riavvio).

### Limitazioni Tecniche
* **Download Backup**: La dimensione dei file di backup scaricabili tramite Telegram è limitata dalle API di Telegram (solitamente 50MB per i bot).
* **Modifiche Resource Pack**: Le modifiche all'ordine o l'aggiunta/rimozione di resource pack diventano effettive solo dopo un riavvio del server (`/restartserver`).

---

## 🛠️ Struttura del Progetto e Script Chiave

Il bot è organizzato in moduli Python per gestire diverse funzionalità:

* `bot.py`: Entry point principale dell'applicazione, inizializza il bot e registra i gestori di comandi.
* `config.py`: Contiene la configurazione del bot, inclusi token, password (lette da `.env`), livelli di autenticazione e percorsi dei file.
* `*_handlers.py`: Diversi file (es. `auth_handlers.py`, `server_handlers.py`, `world_handlers.py`, `structure_handlers.py`, ecc.) contengono la logica per i comandi specifici di Telegram.
* `docker_utils.py`: Utility per interagire con Docker.
* `user_management.py`, `item_management.py`, `world_management.py`, `resource_pack_management.py`: Gestiscono rispettivamente dati utente, oggetti, mondo e resource pack.
* `importBuild/`: Questa cartella contiene script e ambienti per funzionalità avanzate:
    * `lite2Edit/`: Contiene `Lite2Edit.jar` (o lo script per ottenerlo/usarlo) e uno script Python (`litematica_converter.py`) per convertire file `.litematic` in `.schematic`.
    * `schem_to_mc_amulet/`: Contiene script Python che utilizzano Amulet-Core per:
        * `convert2mc.py`: Convertire `.schematic` in `.mcstructure`.
        * `split_mcstructure.py`: Dividere strutture grandi.
        * `pasteStructure.py`: Incollare strutture in un mondo (usato da PasteHologram).
        * `search_armorstand.py`: Rilevare armor stand.
        * `structureInfo.py`: Ottenere informazioni (dimensioni, origine) da file `.mcstructure`.
    * `structura_env/`: Contiene uno script CLI (`structuraCli.py`) e l'ambiente per utilizzare Structura per creare resource pack da file `.mcstructure`.

---

## 🙏 Ringraziamenti e Strumenti Utilizzati

Questo bot è stato reso possibile grazie al lavoro di molte persone e progetti open source. Un ringraziamento speciale a:


* **Python Telegram Bot**: Libreria per l'interazione con le API di Telegram.
    * [Telegram python](https://github.com/python-telegram-bot/python-telegram-bot)
* **Docker**: Per la containerizzazione.
* **itzg/minecraft-bedrock-server**: Container Docker per il server Minecraft Bedrock.
    * [Bedrock docker server](https://github.com/itzg/docker-minecraft-bedrock-server)
* **Amulet Team / Amulet-Core**: Libreria Python per la manipolazione avanzata dei file di mondo e strutture Minecraft.
    * [Amulet-Core ](https://github.com/Amulet-Team/Amulet-Core)
    * [Amulet-Map-Editor ](https://github.com/Amulet-Team/Amulet-Map-Editor)
* **Structura (FlorianMichael, PORK1ELABS, RyanLXXXVII e contributori)**: Strumento per generare resource pack con anteprime 3D delle strutture.
    * [Structura ](https://github.com/StructuraFunc/Structura)
* **Lite2Edit (GoldenDelicios/Creper92yt)**: Strumento (`.jar`) per convertire file `.litematic` in `.schematic`.
    * [Lite2Edit  (Fork GoldenDelicios)](https://github.com/GoldenDelicios/Lite2Edit)
    * *Nota: Autore originale Creper92yt.*
* **nbtlib**: Libreria Python per leggere/modificare file NBT (es. `level.dat`).
    * [nbtlib ](https://github.com/vberlier/nbtlib)
* **Graham Edgecombe**: Per la risorsa degli ID degli oggetti Minecraft.
    * [Minecraft IDs JSON](https://minecraft-ids.grahamedgecombe.com/items.json)

---

## 📄 Licenza

Questo progetto è rilasciato sotto **Licenza MIT**. Vedi il file `LICENSE` (non fornito nei file, ma menzionato nel README originale) per i dettagli completi.

---

*Realizzato con ❤️ per la community Minecraft Bedrock*
