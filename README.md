# Minecraft Bedrock Admin Bot

Questo è un bot Telegram progettato per amministrare un server **Minecraft Bedrock Edition** eseguito in Docker.  
Supporta l'autenticazione degli utenti, l'invio di comandi personalizzati al server, la gestione di inventario con suggerimenti inline, e funzioni interattive come teleport, meteo e distribuzione oggetti.

### ✨ Funzionalità principali

- 🔐 Login con password e gestione utenti autenticati
- 🧾 Lettura dei log del server Minecraft
- 🎮 Comando interattivo `/menu` con pulsanti per teleport, meteo e oggetti
- 📦 Autocompletamento degli oggetti Minecraft tramite query inline
- 🐋 Integrazione con `docker exec` per inviare comandi al container
- 🛡️ Sistema di salvataggio utenti con file `users.json`
- 💾 Backup del mondo con download opzionale via Telegram (NUOVO)

### ⚙️ Requisiti

- Python 3.10+
- Docker con un container Bedrock attivo (`itzg/minecraft-bedrock-server`)
- Token Telegram e password d'accesso

### 🚀 Avvio rapido

1. Clona la repo
2. Crea un file `.env` con le variabili `TELEGRAM_TOKEN`, `BOT_PASSWORD`, e `WORLD_NAME`
3. Avvia il bot con:
4. aggiungi i comandi rapidi da botfather :

menu - Apri il tuo zaino di azioni rapide! 🎒
tp - Teletrasportati come un ninja! 💨
weather - Cambia il meteo... se solo fosse così facile nella vita reale! ☀️🌧️⛈️
give - Regala un oggetto a un amico (o a te stesso!). 🎁
saveloc - Ricorda questo posto magico. 📍
edituser - Modifica il tuo profilo o fai pulizia. ⚙️
cmd - Sussurra comandi direttamente al server. 🤫
logs - Sbircia dietro le quinte del server. 👀
backup_world - Crea un backup del mondo. 💾
list_backups - Mostra e scarica i backup disponibili. 📂 # <<< NUOVO COMANDO PER BOTFATHER
scarica_items - Aggiorna il tuo inventario di meraviglie. ✨
logout - Esci in punta di piedi. 👋
login - Entra nel mondo del bot! 🗝️
startserver - Avvia il server Minecraft. ▶️
stopserver - Ferma il server Minecraft. ⏹️
restartserver - Riavvia il server Minecraft. 🔄
imnotcreative - Resetta il flag creativo del mondo. 🛠️

help - Chiedi aiuto all'esperto bot! ❓