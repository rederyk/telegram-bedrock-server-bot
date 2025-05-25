# Telegram Bedrock Server Admin Bot

Questo è un bot Telegram progettato per amministrare un server **Minecraft Bedrock Edition** eseguito in Docker. Offre un'interfaccia comoda per gestire il server, interagire con i giocatori, automatizzare operazioni comuni e manipolare file di struttura direttamente da Telegram.

Supporta l'autenticazione degli utenti, l'invio di comandi personalizzati al server, la gestione di inventario con suggerimenti inline, funzioni interattive come teleport, meteo, distribuzione oggetti, e strumenti avanzati per la gestione di file `.mcstructure` e `.schematic`.

### ✨ Funzionalità principali

- 🔐 **Autenticazione Sicura:** Login con password configurabile per garantire l'accesso solo agli utenti autorizzati.
- 👤 **Gestione Utenti:** Salva e gestisci gli username Minecraft associati agli utenti Telegram e le loro posizioni salvate.
- 📄 **Monitoraggio Log:** Visualizza gli ultimi log del server Minecraft direttamente in chat.
- 🎒 **Menu Azioni Rapide:** Un menu interattivo (`/menu`) con pulsanti per eseguire rapidamente azioni comuni come dare oggetti, teletrasportarsi e cambiare il meteo.
- 🎁 **Gestione Inventario (`/give`):** Dai oggetti ai giocatori con supporto per la ricerca inline degli item e la specifica della quantità.
- 🚀 **Teletrasporto (`/tp`):** Teletrasporta i giocatori online, usa coordinate specifiche o posizioni salvate.
- ☀️ **Controllo Meteo (`/weather`):** Cambia le condizioni meteorologiche nel mondo di gioco.
- 📍 **Salva Posizione (`/saveloc`):** Salva la tua posizione attuale nel mondo di gioco per poterti teletrasportare facilmente in seguito.
- ⚙️ **Esecuzione Comandi (`/cmd`):** Invia comandi diretti alla console del server Minecraft. Supporta l'invio di più comandi in un singolo messaggio.
- 💾 **Backup del Mondo (`/backup_world`):** Crea backup compressi del mondo di gioco. Richiede l'arresto temporaneo del server.
- 📂 **Lista e Download Backup (`/list_backups`):** Visualizza i backup disponibili e scaricali direttamente tramite Telegram.
- ▶️⏹️🔄 **Gestione Server:** Avvia (`/startserver`), arresta (`/stopserver`) e riavvia (`/restartserver`) il container Docker del server Minecraft.
- 🛠️ **Reset Flag Creativo (`/imnotcreative`):** Resetta il flag che impedisce ai giocatori di uscire dalla modalità creativa nel mondo.
- 📦🖼️ **Gestione Resource Pack:** Aggiungi nuovi resource pack inviando file `.zip` o `.mcpack` (`/addresourcepack`) e gestisci l'ordine o elimina quelli attivi (`/editresourcepacks`).
- ✨ **Aggiornamento Item (`/scarica_items`):** Aggiorna la lista degli oggetti Minecraft disponibili per il comando `/give` e la ricerca inline.
- 🔍 **Ricerca Item Inline:** Cerca oggetti Minecraft direttamente nella chat di Telegram digitando `@nome_bot` seguito dal nome o ID dell'oggetto.
- 🏗️ **Strumenti per Strutture:**
 🧙 - **Wizard Automatico:** Invia un file `.mcstructure`, `.schematic` o `.schem` per avviare un wizard che ti guida nella divisione, conversione e creazione di resource pack.
 ✂️ - **`/split_structure`**: Divide file di struttura (`.mcstructure`/`.schematic`) in parti più piccole.
 🔄 - **`/convert_structure`**: Converte file `.schematic` in formato `.mcstructure`.
 📦 - **`/create_resourcepack`**: Crea un resource pack da uno o più file `.mcstructure` utilizzando Structura.





### ⚙️ Requisiti

- **Python 3.10+:** Assicurati di avere una versione compatibile di Python installata.
- **Docker:** Docker deve essere installato e funzionante sul sistema.
- **Container Minecraft Bedrock:** Un container Docker basato sull'immagine `itzg/minecraft-bedrock-server` (o compatibile) deve essere attivo e configurato. Il bot interagirà con questo container.
- **Token Bot Telegram:** Ottieni un token API per il tuo bot da BotFather su Telegram.
- **Password d'Accesso:** Definisci una password segreta per l'autenticazione degli utenti al bot.
- **Nome del Mondo:** Conosci il nome esatto della directory del mondo Minecraft all'interno del container (es. `Bedrock level`).

### 🚀 Setup e Avvio

1.  **Clona la repository:**
    ```bash
    git clone [https://github.com/tuo_utente/minecraft-telegram-bot.git](https://github.com/tuo_utente/minecraft-telegram-bot.git) # Sostituisci con il tuo URL
    cd minecraft-telegram-bot
    ```

2.  **Installa le dipendenze Python:**
    ```bash
    pip install -r requirements.txt
    # Assicurati che anche le dipendenze per gli script di Amulet e Structura siano disponibili
    # Se esegui il bot in Docker come da docker-compose.yaml fornito, queste sono gestite internamente.
    # Vedi requirements.txt, importBuild/schem_to_mc_amulet/requirements.txt e importBuild/structura_env/requirementsCLI.txt
    ```

3.  **Configura le variabili d'ambiente:**
    Crea un file chiamato `.env` nella directory principale del progetto con il seguente contenuto, sostituendo i valori placeholder:
    ```env
    TELEGRAM_TOKEN="IL_TUO_TOKEN_TELEGRAM"
    BOT_PASSWORD="UNA_PASSWORD_SEGRETA_PER_IL_BOT"
    CONTAINER="nome_o_id_del_tuo_container_minecraft" # Esempio: bds (come da docker-compose.yaml)
    WORLD_NAME="nome_della_tua_directory_mondo" # Esempio: Bedrock level
    # BACKUPS_DIR_NAME="backups" # Opzionale: nome della cartella per i backup dentro /bedrockData. Default: "backups"
    # LOG_LEVEL="INFO" # Opzionale: DEBUG, INFO, WARNING, ERROR, CRITICAL
    ```
    - `TELEGRAM_TOKEN`: Il token API ottenuto da BotFather.
    - `BOT_PASSWORD`: La password che gli utenti dovranno usare con `/login`.
    - `CONTAINER`: Il nome o l'ID del container Docker del tuo server Minecraft. Puoi trovarlo con `docker ps`.
    - `WORLD_NAME`: Il nome della directory del mondo Minecraft. Questo è cruciale per backup, gestione resource pack e il reset del flag creativo. Il percorso base dei dati del server bedrock per il bot è `/bedrockData/` (configurato nel `docker-compose.yaml`).
    - `BACKUPS_DIR_NAME` (Opzionale): Specifica il nome della sottodirectory dentro `/bedrockData/` dove verranno salvati i backup. Se non specificato, verrà usata una directory `backups`.
    - `LOG_LEVEL` (Opzionale): Imposta il livello di logging desiderato (DEBUG, INFO, WARNING, ERROR, CRITICAL). Default: INFO.

4.  **Avvia il bot (o usa Docker Compose):**
    ```bash
    python bot.py
    ```
    Oppure, se usi il `docker-compose.yaml` fornito:
    ```bash
    docker-compose up -d bot bedrock
    ```
    Il bot dovrebbe avviarsi e connettersi a Telegram.

5.  **Configura i comandi rapidi su BotFather:**
    Invia il comando `/setcommands` a BotFather, seleziona il tuo bot e invia la seguente lista di comandi (aggiornata):
    ```
    menu - 🎒 Apri azioni rapide
    tp - 🚀 Teletrasportati
    weather - ☀️ Cambia meteo
    give - 🎁 Dai un oggetto
    saveloc - 📍 Salva posizione
    edituser - 👤 Modifica utente/posizioni
    cmd - ⚙️ Esegui comando server
    logs - 📄 Vedi log server
    backup_world - 💾 Backup mondo
    list_backups - 📂 Lista backup
    addresourcepack - 📦🖼️ Aggiungi resource pack
    editresourcepacks - 📦🛠️ Modifica resource pack
    scarica_items - ✨ Aggiorna lista item
    logout - 👋 Esci dal bot
    login - 🔑 Accedi al bot
    startserver - ▶️ Avvia server MC
    stopserver - ⏹️ Ferma server MC
    restartserver - 🔄 Riavvia server MC
    imnotcreative - 🛠️ Resetta flag creativo
    split_structure - ✂️ Dividi struttura (.mcstructure/.schematic)
    convert_structure - 🔄 Converti .schematic → .mcstructure
    create_resourcepack - 📦 Crea resource pack da .mcstructure
    help - ❓ Aiuto comandi
    ```

### ❓ Guida ai Comandi

Ecco una descrizione più dettagliata di ciascun comando disponibile:

-   `/start`: Messaggio di benvenuto e istruzioni iniziali.
-   `/help`: Mostra la lista dei comandi disponibili con una breve descrizione (come definito nel codice del bot).
-   `/login <password>`: Autentica l'utente al bot utilizzando la password configurata nel file `.env`. Se l'autenticazione ha successo e l'utente non ha ancora un username Minecraft associato, verrà richiesto di inserirlo.
-   `/logout`: Disconnette l'utente dal bot.
-   `/edituser`: Apre un menu per modificare le impostazioni utente, come cambiare l'username Minecraft associato o cancellare le posizioni salvate.
-   `/menu`: Apre un menu interattivo con pulsanti per accedere rapidamente alle funzioni di `/give`, `/tp` e `/weather`. Richiede che l'username Minecraft sia impostato.
-   `/give`: Avvia la procedura guidata per dare un oggetto a te stesso nel gioco. Ti verrà chiesto di inserire il nome o l'ID dell'oggetto, quindi la quantità. Supporta la ricerca inline. Richiede che l'username Minecraft sia impostato e che il container sia configurato.
-   `/tp`: Avvia la procedura guidata per teletrasportarti. Puoi scegliere tra i giocatori online, inserire coordinate specifiche (`x y z`) o selezionare una delle tue posizioni salvate. Richiede che l'username Minecraft sia impostato e che il container sia configurato.
-   `/weather`: Apre un menu per cambiare le condizioni meteo nel mondo di gioco (Sereno, Pioggia, Temporale). Richiede che il container sia configurato.
-   `/saveloc`: Salva la tua posizione attuale nel mondo di gioco con un nome a tua scelta. Ti verrà chiesto di inserire il nome della posizione. Richiede che l'username Minecraft sia impostato e che il container sia configurato.
-   `/cmd <comando>`: Esegue il comando specificato direttamente sulla console del server Minecraft. Puoi inviare più comandi su righe separate. Le righe che iniziano con `#` vengono ignorate come commenti. Richiede che il container sia configurato.
-   `/logs`: Mostra le ultime 50 righe dei log del container Docker del server Minecraft. Richiede che il container sia configurato.
-   `/backup_world`: Crea un backup compresso (.zip) della directory del mondo Minecraft. **ATTENZIONE:** Questo comando arresterà temporaneamente il server per garantire l'integrità del backup. Il server verrà riavviato automaticamente al termine. Richiede che `CONTAINER` e `WORLD_NAME` siano configurati.
-   `/list_backups`: Elenca i backup del mondo disponibili nella directory configurata. Fornisce pulsanti per scaricare i backup direttamente tramite Telegram (limitato ai 15 backup più recenti e con nomi file non eccessivamente lunghi).
-   `/addresourcepack`: Ti chiede di inviare un file `.zip` o `.mcpack` per installarlo come resource pack per il mondo configurato. Il pack verrà aggiunto alla lista attiva con la priorità più alta. Richiede che `WORLD_NAME` sia configurato.
-   `/editresourcepacks`: Mostra la lista dei resource pack attualmente attivi per il mondo configurato. Puoi selezionare un pack per eliminarlo dalla lista attiva o spostarlo per cambiarne la priorità. Richiede che `WORLD_NAME` sia configurato.
-   `/scarica_items`: Aggiorna il file `items.json` scaricando la lista più recente degli oggetti Minecraft. Questo migliora l'accuratezza della ricerca inline e del comando `/give`.
-   `/imnotcreative`: Resetta il flag `hasLoadedInCreative` nel file `level.dat` del mondo. Questo è utile se il mondo è bloccato in modalità creativa. **ATTENZIONE:** Questo comando arresterà temporaneamente il server. Richiede conferma (`/imnotcreative conferma`) prima di procedere. Richiede che `CONTAINER` e `WORLD_NAME` siano configurati.

#### 🏗️ Comandi per Strutture

Questi comandi permettono di manipolare file `.mcstructure` e `.schematic`. Puoi anche **semplicemente inviare un file** (`.mcstructure`, `.schematic`, o `.schem`) al bot per avviare un **wizard automatico** che ti guiderà attraverso i passaggi di divisione, conversione e creazione di resource pack.

-   `/split_structure <path_to_file> [--threshold N] [--axis x|y|z]`:
    Divide un file `.mcstructure` o `.schematic` in parti più piccole. Utile per strutture molto grandi.
    -   `<path_to_file>`: Percorso del file all'interno dell'ambiente del bot (generalmente usato dal wizard).
    -   `--threshold N` (Opzionale): Numero di blocchi oltre il quale dividere (default: 8000).
    -   `--axis x|y|z` (Opzionale): Asse lungo cui dividere (default: automatico tra X e Z).
-   `/convert_structure <path_to_file> [--version X.Y.Z]`:
    Converte un file `.schematic` (Java Edition) in un file `.mcstructure` (Bedrock Edition).
    -   `<path_to_file>`: Percorso del file `.schematic`.
    -   `--version X.Y.Z` (Opzionale): Versione Bedrock per la conversione (default: 1.21).
-   `/create_resourcepack <pack_name> --structures <file1.mcstructure> [<file2.mcstructure> ...] [opzioni]`:
    Crea un resource pack Structura (per visualizzare modelli in gioco) da uno o più file `.mcstructure`.
    -   `<pack_name>`: Nome del pacchetto di output.
    -   `--structures <file.mcstructure> ...`: Uno o più percorsi ai file `.mcstructure`.
    -   `--nametags <tag1> ...` (Opzionale): Nomi per ogni struttura.
    -   `--offsets <x,y,z> ...` (Opzionale): Offset per ogni struttura.
    -   `--opacity N` (Opzionale): Opacità dei blocchi fantasma (0-100, default: 60 per CLI, il wizard chiederà).
    -   `--icon <icon_path>` (Opzionale): Percorso dell'icona del pacchetto.
    -   Vedi `python structuraCli.py --help` nel percorso Structura per tutte le opzioni.

### 🔍 Ricerca Item Inline

Puoi cercare oggetti Minecraft direttamente in qualsiasi chat di Telegram (non solo nella chat privata con il bot) digitando:

`@NomeDelTuoBot <nome_o_id_oggetto>`

Appariranno dei suggerimenti con gli oggetti corrispondenti. Selezionando un suggerimento, verrà inviato un messaggio precompilato con il comando `/give` (potrebbe contenere un placeholder per l'username che dovrai sostituire).

### 🧙 Wizard per File di Struttura

Semplicemente **invia un file `.mcstructure`, `.schematic` o `.schem`** direttamente nella chat con il bot.
Il bot avvierà un wizard automatico:
1.  **Rinomina**: Eventuali file `.schem` verranno rinominati in `.schematic`.
2.  **Divisione (Split)**: Se il file è grande (supera una soglia di blocchi, default ~5000), verrà diviso. Potrai scegliere se:
    * Scaricare i file divisi.
    * Creare resource pack dalle parti divise.
    * Creare un resource pack dalla struttura originale (non divisa).
3.  **Conversione**: I file `.schematic` (originali o divisi) verranno convertiti in `.mcstructure`.
4.  **Creazione Resource Pack**: Ti verrà chiesta l'opacità desiderata (es. 30%, 50%, 80%) e poi verranno creati i file `.mcpack` per ogni struttura `.mcstructure` risultante.
5.  **Download**: I file `.mcpack` generati ti verranno inviati.

### ⚠️ Note Importanti

-   Assicurati che il container Docker del server Minecraft sia accessibile dal sistema dove esegui il bot (o che il bot sia nello stesso network Docker, come nel `docker-compose.yaml`).
-   Il bot utilizza `docker exec` per interagire con il server. L'utente che esegue il bot (o il container del bot) deve avere i permessi necessari per eseguire comandi Docker (generalmente montando `/var/run/docker.sock`).
-   Alcune operazioni (come backup e `/imnotcreative`) richiedono l'arresto e il riavvio del server. Questo causerà una breve interruzione per i giocatori.
-   La gestione dei resource pack modifica il file `world_resource_packs.json` all'interno della directory del mondo. Le modifiche avranno effetto solo dopo un riavvio del server.
-   La funzionalità di download dei backup tramite Telegram ha un limite sulla dimensione del file e sulla lunghezza del nome del file per i bottoni inline. Per backup molto grandi o con nomi lunghi, potrebbe essere necessario accedere direttamente alla directory dei backup sul server.
-   Gli strumenti per le strutture (`split_structure`, `convert_structure`, `create_resourcepack` e il wizard) dipendono da script Python esterni e dalle loro dipendenze (Amulet-Core, Structura). Se si usa il `docker-compose.yaml` fornito, questi dovrebbero essere configurati correttamente all'interno dell'immagine Docker del bot.

### 🤝 Contributi

I contributi sono benvenuti! Se trovi bug o hai idee per nuove funzionalità, apri una issue o invia una pull request.

### 📄 Licenza

Questo progetto è rilasciato sotto licenza MIT. Vedi il file `LICENSE` per i dettagli.

### 🙏 Riconoscimenti

Questo bot utilizza internamente i seguenti fantastici strumenti per alcune delle sue funzionalità di manipolazione delle strutture:

-   **Amulet-Core**: Per la lettura, la scrittura e la conversione di formati di file Minecraft, inclusi `.schematic` e `.mcstructure`. Utilizzato dai comandi `/convert_structure` e `/split_structure` e dal wizard.
-   **Structura**: Per la creazione di resource pack partendo da file `.mcstructure`, permettendo di visualizzare modelli 3D in-game. Utilizzato dal comando `/create_resourcepack` e dal wizard.

Un grande ringraziamento ai creatori e manutentori di questi progetti!
