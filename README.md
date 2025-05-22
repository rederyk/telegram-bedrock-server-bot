# Telegram Bedrock Server Admin Bot

Questo è un bot Telegram progettato per amministrare un server **Minecraft Bedrock Edition** eseguito in Docker. Offre un'interfaccia comoda per gestire il server, interagire con i giocatori e automatizzare alcune operazioni comuni direttamente da Telegram.

Supporta l'autenticazione degli utenti, l'invio di comandi personalizzati al server, la gestione di inventario con suggerimenti inline, e funzioni interattive come teleport, meteo e distribuzione oggetti.

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

### ⚙️ Requisiti

- **Python 3.10+:** Assicurati di avere una versione compatibile di Python installata.
- **Docker:** Docker deve essere installato e funzionante sul sistema.
- **Container Minecraft Bedrock:** Un container Docker basato sull'immagine `itzg/minecraft-bedrock-server` (o compatibile) deve essere attivo e configurato. Il bot interagirà con questo container.
- **Token Bot Telegram:** Ottieni un token API per il tuo bot da BotFather su Telegram.
- **Password d'Accesso:** Definisci una password segreta per l'autenticazione degli utenti al bot.
- **Nome del Mondo:** Conosci il nome esatto della directory del mondo Minecraft all'interno del container.

### 🚀 Setup e Avvio

1. **Clona la repository:**
   ```bash
   git clone https://github.com/tuo_utente/minecraft-telegram-bot.git
   cd minecraft-telegram-bot
   ```

2. **Installa le dipendenze Python:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configura le variabili d'ambiente:**
   Crea un file chiamato `.env` nella directory principale del progetto con il seguente contenuto, sostituendo i valori placeholder:
   ```env
   TELEGRAM_TOKEN="IL_TUO_TOKEN_TELEGRAM"
   BOT_PASSWORD="UNA_PASSWORD_SEGRETA_PER_IL_BOT"
   CONTAINER="nome_o_id_del_tuo_container_minecraft" # Esempio: mc-bedrock-server
   WORLD_NAME="nome_della_tua_directory_mondo" # Esempio: bedrock_world
   # BACKUPS_DIR="/path/assoluto/alla/directory/backup" # Opzionale: specifica una directory diversa per i backup
   # LOG_LEVEL="INFO" # Opzionale: DEBUG, INFO, WARNING, ERROR, CRITICAL
   ```
   - `TELEGRAM_TOKEN`: Il token API ottenuto da BotFather.
   - `BOT_PASSWORD`: La password che gli utenti dovranno usare con `/login`.
   - `CONTAINER`: Il nome o l'ID del container Docker del tuo server Minecraft. Puoi trovarlo con `docker ps`.
   - `WORLD_NAME`: Il nome della directory del mondo Minecraft all'interno del container. Questo è cruciale per backup e gestione resource pack.
   - `BACKUPS_DIR` (Opzionale): Specifica un percorso assoluto sul sistema host dove verranno salvati i backup. Se non specificato, verrà creata una directory `backups` nella stessa directory del bot.
   - `LOG_LEVEL` (Opzionale): Imposta il livello di logging desiderato (DEBUG, INFO, WARNING, ERROR, CRITICAL). Default: INFO.

4. **Avvia il bot:**
   ```bash
   python bot.py
   ```
   Il bot dovrebbe avviarsi e connettersi a Telegram.

5. **Configura i comandi rapidi su BotFather:**
   Invia il comando `/setcommands` a BotFather, seleziona il tuo bot e invia la seguente lista di comandi:
   ```
   menu - Apri il tuo zaino di azioni rapide! 🎒
   tp - Teletrasportati come un ninja! 💨
   weather - Cambia il meteo... se solo fosse così facile nella vita reale! ☀️🌧️⛈️
   give - Regala un oggetto a un amico (o a te stesso!). 🎁
   saveloc - Ricorda questo posto magico. 📍
   edituser - Modifica il tuo profilo o fai pulizia. ⚙️
   cmd - Sussurra comandi direttamente al server. 🤫
   logs - Sbircia dietro le quinte del server. 👀
   backup_world - Crea un backup del mondo. 💾
   list_backups - Mostra e scarica i backup disponibili. 📂
   addresourcepack - Aggiungi un resource pack al mondo. 📦🖼️
   editresourcepacks - Modifica i resource pack attivi del mondo. 📦🛠️
   scarica_items - Aggiorna il tuo inventario di meraviglie. ✨
   logout - Esci in punta di piedi. 👋
   login - Entra nel mondo del bot! 🗝️
   startserver - Avvia il server Minecraft. ▶️
   stopserver - Ferma il server Minecraft. ⏹️
   restartserver - Riavvia il server Minecraft. 🔄
   imnotcreative - Resetta il flag creativo del mondo. 🛠️
   help - Chiedi aiuto all'esperto bot! ❓
   ```

### ❓ Guida ai Comandi

Ecco una descrizione più dettagliata di ciascun comando disponibile:

- `/start`: Messaggio di benvenuto e istruzioni iniziali.
- `/help`: Mostra la lista dei comandi disponibili con una breve descrizione.
- `/login <password>`: Autentica l'utente al bot utilizzando la password configurata nel file `.env`. Se l'autenticazione ha successo e l'utente non ha ancora un username Minecraft associato, verrà richiesto di inserirlo.
- `/logout`: Disconnette l'utente dal bot.
- `/edituser`: Apre un menu per modificare le impostazioni utente, come cambiare l'username Minecraft associato o cancellare le posizioni salvate.
- `/menu`: Apre un menu interattivo con pulsanti per accedere rapidamente alle funzioni di `/give`, `/tp` e `/weather`. Richiede che l'username Minecraft sia impostato.
- `/give`: Avvia la procedura guidata per dare un oggetto a te stesso nel gioco. Ti verrà chiesto di inserire il nome o l'ID dell'oggetto, quindi la quantità. Supporta la ricerca inline. Richiede che l'username Minecraft sia impostato e che il container sia configurato.
- `/tp`: Avvia la procedura guidata per teletrasportarti. Puoi scegliere tra i giocatori online, inserire coordinate specifiche (`x y z`) o selezionare una delle tue posizioni salvate. Richiede che l'username Minecraft sia impostato e che il container sia configurato.
- `/weather`: Apre un menu per cambiare le condizioni meteo nel mondo di gioco (Sereno, Pioggia, Temporale). Richiede che il container sia configurato.
- `/saveloc`: Salva la tua posizione attuale nel mondo di gioco con un nome a tua scelta. Ti verrà chiesto di inserire il nome della posizione. Richiede che l'username Minecraft sia impostato e che il container sia configurato.
- `/cmd <comando>`: Esegue il comando specificato direttamente sulla console del server Minecraft. Puoi inviare più comandi su righe separate. Le righe che iniziano con `#` vengono ignorate come commenti. Richiede che il container sia configurato.
- `/logs`: Mostra le ultime 50 righe dei log del container Docker del server Minecraft. Richiede che il container sia configurato.
- `/backup_world`: Crea un backup compresso (.zip) della directory del mondo Minecraft. **ATTENZIONE:** Questo comando arresterà temporaneamente il server per garantire l'integrità del backup. Il server verrà riavviato automaticamente al termine. Richiede che `CONTAINER` e `WORLD_NAME` siano configurati.
- `/list_backups`: Elenca i backup del mondo disponibili nella directory configurata. Fornisce pulsanti per scaricare i backup direttamente tramite Telegram (limitato ai 15 backup più recenti e con nomi file non eccessivamente lunghi).
- `/addresourcepack`: Ti chiede di inviare un file `.zip` o `.mcpack` per installarlo come resource pack per il mondo configurato. Il pack verrà aggiunto alla lista attiva con la priorità più alta. Richiede che `WORLD_NAME` sia configurato.
- `/editresourcepacks`: Mostra la lista dei resource pack attualmente attivi per il mondo configurato. Puoi selezionare un pack per eliminarlo dalla lista attiva o spostarlo per cambiarne la priorità. Richiede che `WORLD_NAME` sia configurato.
- `/scarica_items`: Aggiorna il file `items.json` scaricando la lista più recente degli oggetti Minecraft. Questo migliora l'accuratezza della ricerca inline e del comando `/give`.
- `/imnotcreative`: Resetta il flag `im_not_creative` nel file `level.dat` del mondo. Questo è utile se il mondo è bloccato in modalità creativa. **ATTENZIONE:** Questo comando arresterà temporaneamente il server. Richiede conferma prima di procedere. Richiede che `CONTAINER` e `WORLD_NAME` siano configurati.

### 🔍 Ricerca Item Inline

Puoi cercare oggetti Minecraft direttamente in qualsiasi chat di Telegram (non solo nella chat privata con il bot) digitando:

`@NomeDelTuoBot <nome_o_id_oggetto>`

Appariranno dei suggerimenti con gli oggetti corrispondenti. Selezionando un suggerimento, verrà inviato un messaggio precompilato con il comando `/give` pronto per essere eseguito (dovrai solo inviarlo al bot).

### ⚠️ Note Importanti

- Assicurati che il container Docker del server Minecraft sia accessibile dal sistema dove esegui il bot.
- Il bot utilizza `docker exec` per interagire con il server. L'utente che esegue il bot deve avere i permessi necessari per eseguire comandi Docker.
- Alcune operazioni (come backup e `/imnotcreative`) richiedono l'arresto e il riavvio del server. Questo causerà una breve interruzione per i giocatori.
- La gestione dei resource pack modifica il file `world_resource_packs.json` all'interno della directory del mondo. Le modifiche avranno effetto solo dopo un riavvio del server.
- La funzionalità di download dei backup tramite Telegram ha un limite sulla dimensione del file e sulla lunghezza del nome del file per i bottoni inline. Per backup molto grandi o con nomi lunghi, potrebbe essere necessario accedere direttamente alla directory dei backup sul server.

### 🤝 Contributi

I contributi sono benvenuti! Se trovi bug o hai idee per nuove funzionalità, apri una issue o invia una pull request.

### 📄 Licenza

Questo progetto è rilasciato sotto licenza MIT. Vedi il file `LICENSE` per i dettagli.
