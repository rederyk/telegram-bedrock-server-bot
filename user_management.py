# minecraft_telegram_bot/user_management.py
import os
import json
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
from config import USERS_FILE, AUTH_PASSWORD, get_logger

logger = get_logger(__name__)

def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE) as f:
            data = json.load(f)
            return {int(k): v for k, v in data.items()}
    except Exception as e:
        logger.error(f"Errore caricamento utenti: {e}")
        return {}

users_data = load_users() # Carica i dati una volta all'avvio
authenticated_users = set(users_data)

def save_users():
    try:
        with open(USERS_FILE, "w") as f:
            json.dump({str(k): v for k, v in users_data.items()}, f, indent=4)
    except Exception as e:
        logger.error(f"Errore salvataggio utenti: {e}")

def is_user_authenticated(user_id: int) -> bool:
    return user_id in authenticated_users

def authenticate_user(user_id: int, password: str) -> bool:
    if password == AUTH_PASSWORD:
        authenticated_users.add(user_id)
        if user_id not in users_data:
            users_data[user_id] = {"minecraft_username": None, "locations": {}}
        save_users()
        return True
    return False

def logout_user(user_id: int):
    authenticated_users.discard(user_id)
    # Non cancelliamo i dati dell'utente da users_data al logout

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
        if "locations" not in users_data[user_id]:
            users_data[user_id]["locations"] = {}
        users_data[user_id]["locations"][loc_name] = coords
        save_users()
        return True
    return False

def get_locations(user_id: int) -> dict:
    user = get_user_data(user_id)
    return user.get("locations", {}) if user else {}

def delete_location(user_id: int, loc_name: str) -> bool:
    if user_id in users_data and "locations" in users_data[user_id] and loc_name in users_data[user_id]["locations"]:
        del users_data[user_id]["locations"][loc_name]
        save_users()
        return True
    return False

def auth_required(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not update.effective_user or not is_user_authenticated(update.effective_user.id):
            await update.message.reply_text("Accesso negato. Usa /login <password>.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper