# minecraft_telegram_bot/config.py
import os
import logging

# --- Config ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
AUTH_PASSWORD = os.getenv("BOT_PASSWORD", "modifica_questa_password")
USERS_FILE = "users.json"
ITEMS_FILE = "items.json"
CONTAINER = "bds"  # Assicurati che questo sia il nome corretto del tuo container Docker

# --- Logging ---
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")

def get_logger(name):
    return logging.getLogger(name)

logger = get_logger(__name__)

# Verifica preliminare delle configurazioni essenziali
if not TOKEN:
    logger.critical("TELEGRAM_TOKEN non impostato. Il bot non può partire.")
if not CONTAINER:
    logger.warning("La variabile CONTAINER non è impostata. Funzionalità server Minecraft limitate.")