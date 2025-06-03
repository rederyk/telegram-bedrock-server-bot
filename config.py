# minecraft_telegram_bot/config.py
import os
import logging

# --- Config ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
# AUTH_PASSWORD = os.getenv("BOT_PASSWORD", "modifica_questa_password") # Removed single password
USERS_FILE = "botData/users.json"
ITEMS_FILE = "items.json"
CONTAINER = "bds"  # Assicurati che questo sia il nome corretto del tuo container Docker
WORLD_NAME = os.getenv("WORLD_NAME", "Bedrock level") # Default or from .env
BACKUPS_DIR_NAME = "backups"

# --- Authentication Levels ---
AUTH_LEVELS = {
    
    "custom": {
        "password": os.getenv("CUSTOM_PASSWORD", "custom_password"),
        "permissions": ["give", "tp"]
    },
    "basic": {
        "password": os.getenv("BASIC_PASSWORD", "basic_password"),
        "permissions": ["menu", "give", "tp", "saveloc"]
    },
    
    "player": {
        "password": os.getenv("PLAYER_PASSWORD", "player_password"),
        "permissions": ["menu", "give", "tp", "saveloc", "weather", "stopserver", "restartserver", "backup_world", "imnotcreative", "scarica_items", "addresourcepack", "editresourcepacks", "split_structure", "convert_structure", "create_resourcepack"]
    },
    "moderator": {
        "password": os.getenv("MODERATOR_PASSWORD", "moderator_password"),
        "permissions": ["menu", "give", "tp", "saveloc", "weather", "logs", "cmd", "stopserver", "restartserver", "backup_world", "imnotcreative", "scarica_items", "addresourcepack", "editresourcepacks", "split_structure", "convert_structure", "create_resourcepack"]
    },
    "admin": {
        "password": os.getenv("ADMIN_PASSWORD", "admin_password"),
        "permissions": ["menu", "give", "tp", "saveloc", "weather", "logs", "cmd", "stopserver", "restartserver", "backup_world", "list_backups", "imnotcreative", "scarica_items", "addresourcepack", "editresourcepacks", "split_structure", "convert_structure", "create_resourcepack"]
    }
}

# --- Logging ---
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")

def get_logger(name):
    return logging.getLogger(name)

logger = get_logger(__name__)

# Verifica preliminare delle configurazioni essenziali
if not TOKEN:
    logger.critical("🚨 TOKEN Telegram mancante! Il bot non può avviarsi.")
if not CONTAINER:
    logger.warning("⚠️  CONTAINER non impostato. Funzionalità server limitate.")
if not WORLD_NAME:
    logger.warning("⚠️  WORLD_NAME non impostato. Funzionalità mondo (backup, RP) limitate.")
