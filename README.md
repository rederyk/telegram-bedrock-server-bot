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

```bash
python bot.py
