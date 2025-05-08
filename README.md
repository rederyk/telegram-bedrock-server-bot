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

### ⚙️ Requisiti

- Python 3.10+
- Docker con un container Bedrock attivo (`itzg/minecraft-bedrock-server`)
- Token Telegram e password d'accesso

### 🚀 Avvio rapido

1. Clona la repo
2. Crea un file `.env` con le variabili `TELEGRAM_TOKEN` e `BOT_PASSWORD`
3. Avvia il bot con:
4. aggiungi i comandi rapidi da botfather :
```
menu - Apri il tuo zaino di azioni rapide! 🎒
tp - Teletrasportati come un ninja! 💨
weather - Cambia il meteo... se solo fosse così facile nella vita reale! ☀️🌧️⛈️
give - Regala un oggetto a un amico (o a te stesso!). 🎁
saveloc - Ricorda questo posto magico. 📍
edituser - Modifica il tuo profilo o fai pulizia. ⚙️
cmd - Sussurra comandi direttamente al server. 🤫
logs - Sbircia dietro le quinte del server. 👀
scarica_items - Aggiorna il tuo inventario di meraviglie. ✨
logout - Esci in punta di piedi. 👋
login - Entra nel mondo del bot! 🗝️


# TODO
- use ssh instead of docker attach
help - Chiedi aiuto all'esperto bot! ❓
```
```bash
python bot.py
