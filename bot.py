import os
import json
import logging
import subprocess
import requests
import uuid

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InlineQueryResultArticle, InputTextMessageContent
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, InlineQueryHandler,
    ContextTypes, filters
)

# --- Config ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
AUTH_PASSWORD = os.getenv("BOT_PASSWORD", "modifica_questa_password")
USERS_FILE = "users.json"
ITEMS_FILE = "items.json"
CONTAINER = "bds"

# --- Logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- User Management ---
def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE) as f:
            data = json.load(f)
            return {int(k): v for k, v in data.items()}
    except Exception as e:
        logging.error(f"Errore caricamento utenti: {e}")
        return {}

def save_users():
    try:
        with open(USERS_FILE, "w") as f:
            json.dump({str(k): v for k, v in users.items()}, f, indent=4)
    except Exception as e:
        logging.error(f"Errore salvataggio utenti: {e}")

users = load_users()
authenticated = set(users)

# --- Items Management ---
def fetch_items():
    try:
        r = requests.get("http://minecraft-ids.grahamedgecombe.com/items.json", timeout=10)
        r.raise_for_status()
        items = []
        for item in r.json():
            if isinstance(item, dict) and "text_type" in item and "name" in item:
                items.append({
                    "id": f"minecraft:{item['text_type']}",
                    "name": item["name"]
                })
        with open(ITEMS_FILE, "w") as f:
            json.dump(items, f, indent=2)
        logging.info(f"Scaricati e salvati {len(items)} item.")
        return items
    except Exception as e:
        logging.error(f"Errore scaricamento item list: {e}")
        return []

def load_items():
    if os.path.exists(ITEMS_FILE):
        try:
            with open(ITEMS_FILE) as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Errore caricamento items.json: {e}")
    return fetch_items()

ITEMS = load_items()

# --- Utils ---
def is_authenticated(user_id: int) -> bool:
    return user_id in authenticated

def get_online_players():
    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", "100", CONTAINER],
            capture_output=True, text=True, timeout=5
        )
        output = result.stdout or ""
        lines = output.splitlines()
        for i in reversed(range(len(lines))):
            if "players online:" in lines[i].lower() and i + 1 < len(lines):
                return [p.strip() for p in lines[i + 1].split(",") if p.strip()]
    except Exception as e:
        logging.error(f"Errore ottenendo giocatori online: {e}")
    return []

def auth_required(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_authenticated(update.effective_user.id):
            await update.message.reply_text("Accesso negato. Usa /login <password>.")
            return
        return await func(update, context)
    return wrapper

# --- Comandi ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot Minecraft attivo. Usa /login <password> per iniziare.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Comandi:\n"
        "/login <password> - Autenticati\n"
        "/logout - Esci\n"
        "/menu - Mostra comandi\n"
        "/logs - Mostra log\n"
        "/scarica_items - Aggiorna lista oggetti\n"
        "Puoi anche digitare @<nome_bot> + nome oggetto per suggerimenti inline."
    )

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    args = context.args
    if is_authenticated(uid):
        await update.message.reply_text("Sei già autenticato.")
        return
    if not args or args[0] != AUTH_PASSWORD:
        await update.message.reply_text("Password errata.")
        return
    authenticated.add(uid)
    if uid not in users:
        users[uid] = {"minecraft_username": None}
    save_users()
    await update.message.reply_text("Autenticazione avvenuta.")
    if not users[uid]["minecraft_username"]:
        context.user_data["awaiting_mc_username"] = True
        await update.message.reply_text("Inserisci ora il tuo nome utente Minecraft:")



@auth_required
async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    authenticated.discard(uid)
    if uid in users:
        del users[uid]
        save_users()
    await update.message.reply_text("Logout eseguito. Il tuo nome utente Minecraft è stato rimosso.")

@auth_required
async def logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", "50", CONTAINER],
            capture_output=True, text=True, check=True, timeout=10
        )
        output = result.stdout.strip() or "(Nessun output)"
        safe = output.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        msg = f"<b>Ultimi 50 log:</b>\n<pre>{safe[:3900]}</pre>"
        await update.message.reply_text(msg, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"Errore: {e}")

@auth_required
async def cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    command_text = update.message.text.partition(" ")[2].strip()
    if not command_text:
        await update.message.reply_text("Specifica un comando da inviare. Esempio: /cmd list")
        return
    try:
        subprocess.run(
            ["docker", "exec", CONTAINER, "send-command", command_text],
            check=True, timeout=10
        )
        await update.message.reply_text(
            f"Comando inviato: {command_text}\nControlla /logs per l'output."
        )
    except subprocess.CalledProcessError as e:
        await update.message.reply_text(f"Errore eseguendo il comando:\n{e}")
    except Exception as e:
        await update.message.reply_text(f"Errore imprevisto:\n{e}")

@auth_required
async def scarica_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ITEMS
    ITEMS = fetch_items()
    await update.message.reply_text(f"Scaricati {len(ITEMS)} item da Minecraft.")




@auth_required
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not users[uid].get("minecraft_username"):
        context.user_data["awaiting_mc_username"] = True
        await update.message.reply_text("Inserisci prima il tuo nome utente Minecraft:")
        return
    kb = [
        [InlineKeyboardButton("Give item", callback_data="give")],
        [InlineKeyboardButton("Teleport", callback_data="tp")],
        [InlineKeyboardButton("Meteo", callback_data="weather")]
    ]
    await update.message.reply_text("Scegli un comando:", reply_markup=InlineKeyboardMarkup(kb))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()

    if context.user_data.get("awaiting_mc_username"):
        users[uid]["minecraft_username"] = text
        save_users()
        context.user_data["awaiting_mc_username"] = False
        await update.message.reply_text(f"Username Minecraft salvato: {text}")
        return

    if context.user_data.get("awaiting_give_prefix"):
        prefix = text.lower()
        matches = [i for i in ITEMS if i["id"].startswith(prefix) or i["name"].lower().startswith(prefix)]
        if not matches:
            await update.message.reply_text("Nessun item trovato.")
            return
        buttons = [
            InlineKeyboardButton(f'{i["name"]} ({i["id"]})', callback_data=f'give_item:{i["id"]}')
            for i in matches[:10]
        ]
        keyboard = [buttons[i:i+1] for i in range(len(buttons))]
        await update.message.reply_text("Scegli un item:", reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data["awaiting_give_prefix"] = False
        return

    if context.user_data.get("awaiting_item_quantity"):
        try:
            quantity = int(text)
            if quantity <= 0:
                raise ValueError
            item = context.user_data.get("selected_item")
            if not item:
                await update.message.reply_text("Errore interno: item mancante.")
                return
            mc = users[uid]["minecraft_username"]
            cmd = f"give {mc} {item} {quantity}"
            subprocess.run(["docker", "exec", CONTAINER, "send-command", cmd])
            await update.message.reply_text(f"Comando eseguito: {cmd}")
        except ValueError:
            await update.message.reply_text("Inserisci un numero valido maggiore di zero.")
        finally:
            context.user_data.pop("selected_item", None)
            context.user_data["awaiting_item_quantity"] = False
        return

    if context.user_data.get("awaiting_tp_coords"):
        parts = text.split()
        if len(parts) != 3:
            await update.message.reply_text("Formato non valido. Usa: x y z")
            return
        try:
            x, y, z = map(float, parts)
            mc = users[uid]["minecraft_username"]
            cmd = f"tp {mc} {x} {y} {z}"
            subprocess.run(["docker", "exec", CONTAINER, "send-command", cmd])
            await update.message.reply_text(f"Comando eseguito: {cmd}")
        except ValueError:
            await update.message.reply_text("Le coordinate devono essere numeri validi.")
        finally:
            context.user_data["awaiting_tp_coords"] = False
        return

    await update.message.reply_text("Comando non riconosciuto. Usa /menu.")

async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip().lower()
    if not query:
        return
    matches = [i for i in ITEMS if i["id"].startswith(query) or i["name"].lower().startswith(query)]
    results = [
        InlineQueryResultArticle(
            id=str(uuid.uuid4()),
            title=f'{i["name"]} ({i["id"]})',
            input_message_content=InputTextMessageContent(i["id"])
        )
        for i in matches[:10]
    ]
    await update.inline_query.answer(results, cache_time=1)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    mc = users[uid]["minecraft_username"]
    data = query.data

    if data == "give":
        context.user_data["awaiting_give_prefix"] = True
        await query.edit_message_text("Scrivi il prefisso dell'item:")

        
    elif data.startswith("give_item:"):
        item = data.split(":", 1)[1]
        context.user_data["selected_item"] = item
        context.user_data["awaiting_item_quantity"] = True
        await query.edit_message_text("Inserisci la quantità desiderata:")

    elif data == "tp":
        players = get_online_players()
        buttons = [InlineKeyboardButton(p, callback_data=f"tp_player:{p}") for p in players]
        buttons.append(InlineKeyboardButton("📍 Inserisci coordinate", callback_data="tp_coords"))
        keyboard = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
        await query.edit_message_text("Scegli il giocatore o inserisci coordinate:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "tp_coords":
        context.user_data["awaiting_tp_coords"] = True
        await query.edit_message_text("Inserisci le coordinate nel formato: `x y z`")


    elif data.startswith("tp_player:"):
        target = data.split(":", 1)[1]
        cmd = f"tp {mc} {target}"
        subprocess.run(["docker", "exec", CONTAINER, "send-command", cmd])
        await query.edit_message_text(f"Comando eseguito: {cmd}")
    elif data == "weather":
        buttons = [[InlineKeyboardButton(w, callback_data=f"weather_set:{w}")] for w in ["clear", "rain", "thunder"]]
        await query.edit_message_text("Scegli il meteo:", reply_markup=InlineKeyboardMarkup(buttons))
    elif data.startswith("weather_set:"):
        weather = data.split(":", 1)[1]
        cmd = f"weather {weather}"
        subprocess.run(["docker", "exec", CONTAINER, "send-command", cmd])
        await query.edit_message_text(f"Meteo impostato su: {weather}")
    else:
        await query.edit_message_text("Comando non valido.")

# --- Main ---
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("logs", logs))
    app.add_handler(CommandHandler("scarica_items", scarica_items))
    app.add_handler(CommandHandler("cmd", cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(InlineQueryHandler(inline_query_handler))
    logging.info("Bot avviato.")
    app.run_polling()

if __name__ == "__main__":
    main()
