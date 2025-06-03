# minecraft_telegram_bot/user_management.py
import os
import json
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
from config import USERS_FILE, get_logger

logger = get_logger(__name__)

def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE) as f:
            data = json.load(f)
            # Converte le chiavi in int poiché JSON le salva come stringhe
            return {int(k): v for k, v in data.items()}
    except Exception as e:
        logger.error(f"👤❌ Errore caricamento {USERS_FILE}: {e}")
        return {}

users_data = load_users()
authenticated_users = set(users_data)

def save_users():
    try:
        with open(USERS_FILE, "w") as f:
            # Converte le chiavi int in stringhe per la serializzazione JSON
            json.dump({str(k): v for k, v in users_data.items()}, f, indent=4)
    except Exception as e:
        logger.error(f"👤❌ Errore salvataggio {USERS_FILE}: {e}")

def is_user_authenticated(user_id: int) -> bool:
    return user_id in authenticated_users

from config import AUTH_LEVELS

def authenticate_user(user_id: int, password: str) -> bool:
    for auth_level, level_data in AUTH_LEVELS.items():
        if password == level_data["password"]:
            if user_id not in users_data: # Aggiungi nuovo utente se non esiste
                users_data[user_id] = {"minecraft_username": None, "locations": {}, "auth_level": auth_level}
            else:
                users_data[user_id]["auth_level"] = auth_level
            authenticated_users.add(user_id)
            save_users() # Salva dopo ogni modifica
            logger.info(f"users_data after auth: {users_data}")
            return True
    return False

def logout_user(user_id: int):
    authenticated_users.discard(user_id)
    if user_id in users_data:
        del users_data[user_id]
        save_users()

def get_user_data(user_id: int) -> dict | None:
    return users_data.get(user_id)

def set_minecraft_username(user_id: int, username: str):
    if user_id in users_data:
        users_data[user_id]["minecraft_username"] = username
        save_users()
        return True
    return False

def get_minecraft_username(user_id: int) -> str | None:
    user = get_user_data(user_id)
    return user.get("minecraft_username") if user else None

def save_location(user_id: int, loc_name: str, coords: dict):
    if user_id in users_data:
        if "locations" not in users_data[user_id]: # Assicura che la chiave esista
            users_data[user_id]["locations"] = {}
        users_data[user_id]["locations"][loc_name] = coords
        save_users()
        return True
    return False

def get_locations(user_id: int) -> dict:
    user = get_user_data(user_id)
    return user.get("locations", {}) if user else {} # Restituisce dict vuoto se non ci sono locazioni

def delete_location(user_id: int, loc_name: str) -> bool:
    if user_id in users_data and "locations" in users_data[user_id] and loc_name in users_data[user_id]["locations"]:
        del users_data[user_id]["locations"][loc_name]
        save_users()
        return True
    return False

def auth_required(required_permissions):
    def decorator(func):
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user_id = update.effective_user.id if update.effective_user else None
            if not user_id or not is_user_authenticated(user_id):
                await update.message.reply_text("Accesso negato. Usa /login <password>.")
                return

            user_data = get_user_data(user_id)
            if not user_data or "auth_level" not in user_data:
                await update.message.reply_text("Accesso negato: livello di autorizzazione insufficiente.")
                return

            auth_level = user_data["auth_level"]
            if auth_level not in AUTH_LEVELS:
                await update.message.reply_text("Accesso negato: livello di autorizzazione non valido.")
                return

            user_permissions = AUTH_LEVELS[auth_level]["permissions"]

            if "*" not in user_permissions and not all(perm in user_permissions for perm in required_permissions):
                await update.message.reply_text("Accesso negato: permessi insufficienti.")
                return

            return await func(update, context, *args, **kwargs)
        return wrapper
    return decorator
