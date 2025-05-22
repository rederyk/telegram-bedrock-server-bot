# Minecraft Bedrock Admin Bot

Questo è un bot Telegram progettato per amministrare un server **Minecraft Bedrock Edition** eseguito in Docker.
Supporta l'autenticazione degli utenti, l'invio di comandi personalizzati al server, la gestione di inventario con suggerimenti inline, funzioni interattive come teleport, meteo, distribuzione oggetti, gestione dei backup e gestione avanzata dei resource pack.

### ✨ Funzionalità principali

- 🔐 Login con password e gestione utenti autenticati
- 🧾 Lettura dei log del server Minecraft
- 🎮 Comando interattivo `/menu` con pulsanti per teleport, meteo e oggetti
- 📦 Autocompletamento degli oggetti Minecraft tramite query inline
- 🐋 Integrazione con `docker exec` per inviare comandi al container
- 🛡️ Sistema di salvataggio utenti con file `users.json`
- 💾 Backup del mondo con download opzionale via Telegram
- 🖼️ Aggiunta di resource pack al mondo tramite file o URL (NUOVO)
- ⚙️ Modifica dell'ordine di caricamento e rimozione dei resource pack attivi (NUOVO)

### ⚙️ Requisiti

- Python 3.10+
- Docker con un container Bedrock attivo (es. `itzg/minecraft-bedrock-server`)
- Token Telegram e password d'accesso per il bot
- Variabile d'ambiente `WORLD_NAME` configurata con il nome del mondo target.

### 🚀 Avvio rapido

1.  Clona la repository: `git clone <url_repository>`
2.  Entra nella directory: `cd minecraft-bedrock-admin-bot`
3.  Crea un file `.env` nella directory principale del progetto con le seguenti variabili:
    ```env
    TELEGRAM_TOKEN=IL_TUO_TOKEN_TELEGRAM
    BOT_PASSWORD=UNA_PASSWORD_SICURA_PER_IL_BOT
    WORLD_NAME=NomeDelTuoMondoMinecraft
    # CONTAINER_NAME=bds (opzionale, default è 'bds')
    ```
    Sostituisci `IL_TUO_TOKEN_TELEGRAM`, `UNA_PASSWORD_SICURA_PER_IL_BOT` e `NomeDelTuoMondoMinecraft` con i tuoi valori effettivi. `WORLD_NAME` deve corrispondere al nome della cartella del mondo o al nome specificato nella configurazione del server Bedrock.
4.  Assicurati che Docker sia in esecuzione e che il container del server Minecraft (chiamato 'bds' per impostazione predefinita, o come specificato in `CONTAINER_NAME`) sia configurato e, preferibilmente, in esecuzione.
5.  Costruisci l'immagine Docker del bot (se usi Docker per il bot):
    `docker-compose build bot`
6.  Avvia il bot (e il server Minecraft, se definito nel `docker-compose.yaml`):
    `docker-compose up -d` (o `python bot.py` se esegui localmente dopo aver installato i requisiti da `requirements.txt`)

7.  Configura i comandi rapidi per il tuo bot su Telegram parlando con @BotFather. Incolla la seguente lista:

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
addresourcepack - Aggiungi un resource pack al mondo. 🖼️
editresourcepacks - Modifica i resource pack attivi. 🛠️
scarica_items - Aggiorna il tuo inventario di meraviglie. ✨
logout - Esci in punta di piedi. 👋
login - Entra nel mondo del bot! 🗝️
startserver - Avvia il server Minecraft. ▶️
stopserver - Ferma il server Minecraft. ⏹️
restartserver - Riavvia il server Minecraft. 🔄
imnotcreative - Resetta il flag creativo del mondo. 🛠️
help - Chiedi aiuto all'esperto bot! ❓
```

### 🔧 Configurazione

-   **`config.py`**: Contiene le impostazioni principali come il token, la password, i nomi dei file e il nome del container Docker. Molte di queste sono caricate da variabili d'ambiente.
-   **`users.json`**: File generato automaticamente per memorizzare gli ID utente autenticati e i loro dati (come l'username Minecraft e le posizioni salvate).
-   **`items.json`**: Cache locale della lista degli item di Minecraft, scaricata da una fonte online.
-   **`docker-compose.yaml`**: Configurazione di esempio per eseguire il bot e il server Minecraft Bedrock con Docker. Assicurati che i volumi siano mappati correttamente per permettere al bot di accedere ai file del server (es. `level.dat`, `world_resource_packs.json`, cartella `resource_packs`). La cartella `/bedrockData` usata dal bot nel `docker-compose.yaml` deve puntare alla directory dei dati del server Minecraft.

### 📁 Struttura dei file del server Minecraft (rilevante per il bot)

Il bot si aspetta una struttura di directory simile a quella creata da `itzg/minecraft-bedrock-server` quando i dati sono montati su `/bedrockData` per il bot:

-   `/bedrockData/worlds/<WORLD_NAME>/level.dat`
-   `/bedrockData/worlds/<WORLD_NAME>/world_resource_packs.json`
-   `/bedrockData/resource_packs/` (qui verranno copiati i nuovi resource pack .zip)
-   `/bedrockData/backups/` (qui verranno salvati i backup del mondo)

Assicurati che i permessi dei file e delle cartelle consentano al bot (eseguito dall'utente Docker, di solito root) di leggere e scrivere dove necessario.

### ⚠️ Note Importanti

-   **Sicurezza**: Usa una password robusta per `BOT_PASSWORD`.
-   **`WORLD_NAME`**: Questa variabile è cruciale. Deve corrispondere esattamente al nome della cartella del mondo come appare nel filesystem del server (es. "Bedrock level" o il nome personalizzato che hai dato).
-   **Permessi Docker**: Il bot necessita dell'accesso al socket Docker (`/var/run/docker.sock`) per gestire i container.
-   **Resource Pack**: 
    - L'ordine di caricamento dei resource pack in Minecraft Bedrock è inverso rispetto a come appaiono nel file `world_resource_packs.json`: il primo pacchetto nella lista ha la priorità più bassa, l'ultimo pacchetto nella lista ha la priorità più alta (viene visualizzato sopra gli altri).
    - Quando aggiungi un resource pack con `/addresourcepack`, viene messo alla fine della lista (priorità più alta).
    - Dopo aver aggiunto, rimosso o modificato l'ordine dei resource pack, è fortemente consigliato riavviare il server Minecraft per assicurarsi che le modifiche vengano applicate correttamente a tutti i giocatori. Il bot offrirà di farlo.
