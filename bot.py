import os
import json
import logging
import subprocess
import asyncio  # Aggiunto per operazioni asincrone
import requests
import uuid
import re # Importa re per saveloc

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InlineQueryResultArticle, InputTextMessageContent
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, InlineQueryHandler,
    ContextTypes, filters
)
from telegram.constants import ParseMode  # Importato per ParseMode.HTML

# --- Config ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
AUTH_PASSWORD = os.getenv("BOT_PASSWORD", "modifica_questa_password")
USERS_FILE = "users.json"
ITEMS_FILE = "items.json"
CONTAINER = "bds"  # Assicurati che questo sia il nome corretto del tuo container Docker

# --- Logging ---
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")

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
        # Nota: requests è sincrono. Per un bot completamente asincrono, considera aiohttp.
        r = requests.get(
            "http://minecraft-ids.grahamedgecombe.com/items.json", timeout=10)
        r.raise_for_status()
        items_data = []
        for item in r.json():
            if isinstance(item, dict) and "text_type" in item and "name" in item:
                items_data.append({
                    "id": f"minecraft:{item['text_type']}",
                    "name": item["name"]
                })
        with open(ITEMS_FILE, "w") as f:
            json.dump(items_data, f, indent=2)
        logging.info(f"Scaricati e salvati {len(items_data)} item.")
        return items_data
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

# --- Async Docker Execution Helper ---


async def run_docker_command(command_args, read_output=False, timeout=15):
    """
    Esegue asincronamente un comando Docker.
    Args:
        command_args (list): Il comando e i suoi argomenti.
        read_output (bool): Se True, restituisce stdout. Altrimenti, il codice di ritorno.
        timeout (int): Timeout in secondi.
    Returns:
        str or int: stdout se read_output è True, altrimenti il codice di ritorno del processo.
    Raises:
        asyncio.TimeoutError: Se il comando va in timeout.
        subprocess.CalledProcessError: Se il comando restituisce un codice di errore.
        Exception: Per altri errori durante l'esecuzione.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            *command_args,
            stdout=asyncio.subprocess.PIPE if read_output else asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)

        decoded_stderr = stderr.decode().strip() if stderr else ""
        if decoded_stderr:
            logging.info(
                f"Output stderr dal comando Docker '{' '.join(command_args)}': {decoded_stderr}")

        if process.returncode != 0:
            logging.warning(
                f"Comando Docker '{' '.join(command_args)}' ha restituito {process.returncode}. stderr: {decoded_stderr}")
            # Non sollevare eccezione per alcuni comandi che potrebbero comportarsi così
            # if not ("send-command" in command_args and "list" in command_args): # Esempio di eccezione
            raise subprocess.CalledProcessError(
                process.returncode, command_args,
                output=stdout.decode().strip() if stdout else None,
                stderr=decoded_stderr
            )

        if read_output:
            return stdout.decode().strip()
        return process.returncode
    except asyncio.TimeoutError:
        logging.error(
            f"Timeout per il comando Docker: {' '.join(command_args)}")
        raise
    except subprocess.CalledProcessError:  # Rilancia per essere gestita dal chiamante
        raise
    except Exception as e:
        logging.error(
            f"Errore imprevisto eseguendo il comando Docker {' '.join(command_args)}: {e}")
        raise


# --- Utils ---
def is_authenticated(user_id: int) -> bool:
    return user_id in authenticated

# --- MODIFIED get_online_players function ---


async def get_online_players():
    """
    Ottiene la lista dei giocatori online eseguendo prima il comando /list sul server
    e poi parsando i log recenti.
    """
    if not CONTAINER:
        logging.error(
            "Variabile CONTAINER non impostata, impossibile ottenere i giocatori online.")
        return []
    try:
        list_command_args = ["docker", "exec",
                             CONTAINER, "send-command", "list"]
        logging.info(
            f"Esecuzione comando per aggiornare lista giocatori: {' '.join(list_command_args)}")
        try:
            await run_docker_command(list_command_args, read_output=False, timeout=5)
        except subprocess.CalledProcessError as e:
            logging.warning(
                f"Comando '{' '.join(list_command_args)}' ha restituito un errore (codice {e.returncode}), ma si procede con la lettura dei log. Stderr: {e.stderr}")
        except asyncio.TimeoutError:
            logging.error(
                f"Timeout durante l'esecuzione del comando '{' '.join(list_command_args)}'. Impossibile aggiornare la lista giocatori.")
            return []
        except Exception as e:
            logging.error(
                f"Errore imprevisto eseguendo '{' '.join(list_command_args)}': {e}. Si tenta comunque di leggere i log.")

        await asyncio.sleep(1.0)

        logs_command_args = ["docker", "logs", "--tail", "100", CONTAINER]
        logging.info(f"Lettura log: {' '.join(logs_command_args)}")
        output = await run_docker_command(logs_command_args, read_output=True, timeout=5)

        if not output:
            logging.warning("Nessun output dai log dopo il comando list.")
            return []

        lines = output.splitlines()
        player_list = []

        for i in reversed(range(len(lines))):
            current_line_raw = lines[i]
            current_line_content = current_line_raw

            if "]: " in current_line_content:
                current_line_content = current_line_content.split("]: ", 1)[1]
            elif "] " in current_line_content:
                current_line_content = current_line_content.split("] ", 1)[1]

            current_line_lower = current_line_content.lower()

            if ("players online:" in current_line_lower and "there are" in current_line_lower) or \
               ("players online:" in current_line_lower):

                if ":" in current_line_content:
                    potential_players_str = current_line_content.split(":", 1)[
                        1].strip()
                    if potential_players_str:
                        if "max players online" not in current_line_lower:
                            player_list = [p.strip() for p in potential_players_str.split(',') if p.strip(
                            ) and "no players online" not in p.lower() and "nessun giocatore connesso" not in p.lower()]
                            if player_list:
                                logging.info(
                                    f"Giocatori online trovati (stessa riga): {player_list}")
                                return player_list

                if i + 1 < len(lines):
                    next_line_raw = lines[i+1]
                    next_line_content = next_line_raw
                    if "]: " in next_line_content:
                        next_line_content = next_line_content.split("]: ", 1)[
                            1]
                    elif "] " in next_line_content:
                        next_line_content = next_line_content.split("] ", 1)[1]

                    next_line_content_stripped = next_line_content.strip()

                    if next_line_content_stripped and not next_line_content_stripped.startswith("[") and " INFO" not in next_line_raw and " WARN" not in next_line_raw and " ERROR" not in next_line_raw:
                        if "no players online" not in next_line_content_stripped.lower() and "nessun giocatore connesso" not in next_line_content_stripped.lower():
                            player_list = [
                                p.strip() for p in next_line_content_stripped.split(',') if p.strip()]
                            if player_list:
                                logging.info(
                                    f"Giocatori online trovati (riga successiva): {player_list}")
                                return player_list
                logging.info(
                    "Trovato 'players online:' ma nessun giocatore elencato o lista vuota.")
                return []
        logging.info(
            "Pattern 'players online:' non trovato nei log recenti dopo il comando 'list'.")
        return []
    except asyncio.TimeoutError:
        logging.error(
            "Timeout ottenendo i giocatori online (fase lettura log).")
    except subprocess.CalledProcessError as e:
        logging.error(
            f"Errore comando Docker leggendo i log per get_online_players: {e.cmd} - {e.stderr or e.output or e}")
    except Exception as e:
        logging.error(
            f"Errore generico ottenendo giocatori online: {e}", exc_info=True)
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
        "/menu - Mostra menu azioni rapide\n"
        "/give - Avvia il flusso per dare un oggetto\n"
        "/tp - Avvia il flusso di teletrasporto\n"
        "/weather - Avvia il flusso per cambiare meteo\n"
        "/saveloc - Salva la tua posizione attuale\n"
        "/edituser - Modifica username o cancella posizioni\n"
        "/cmd <comando_minecraft> - Esegui comando server (es. /cmd list)\n"
        "/logs - Mostra ultimi log del server\n"
        "/scarica_items - Aggiorna lista oggetti Minecraft\n"
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
    if not users[uid].get("minecraft_username"):
        context.user_data["awaiting_mc_username"] = True
        await update.message.reply_text("Per favore, inserisci ora il tuo nome utente Minecraft:")


@auth_required
async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    authenticated.discard(uid)
    await update.message.reply_text("Logout eseguito.")


@auth_required
async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CONTAINER:
        await update.message.reply_text("Variabile CONTAINER non impostata. Impossibile recuperare i log.")
        return
    try:
        command_args = ["docker", "logs", "--tail", "50", CONTAINER]
        output = await run_docker_command(command_args, read_output=True, timeout=10)
        output = output or "(Nessun output dai log)"
        safe_output = output.replace("&", "&amp;").replace(
            "<", "&lt;").replace(">", "&gt;")
        msg = f"<b>Ultimi 50 log del server:</b>\n<pre>{safe_output[:3900]}</pre>"
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except asyncio.TimeoutError:
        await update.message.reply_text("Errore: Timeout durante il recupero dei log.")
    except subprocess.CalledProcessError as e:
        await update.message.reply_text(f"Errore nel comando Docker per i log: {e.stderr or e.output or e}")
    except Exception as e:
        await update.message.reply_text(f"Errore imprevisto recuperando i log: {e}")


@auth_required
async def edituser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("✏️ Modifica username", callback_data="edit_username")],
        [InlineKeyboardButton("🗑️ Cancella posizione salvata", callback_data="delete_location")],
    ]
    await update.message.reply_text(
        "Cosa vuoi fare?",
        reply_markup=InlineKeyboardMarkup(kb)
    )


@auth_required
async def cmd_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CONTAINER:
        await update.message.reply_text("Variabile CONTAINER non impostata. Impossibile eseguire comandi.")
        return
    command_text = " ".join(context.args).strip()
    if not command_text:
        await update.message.reply_text("Specifica un comando da inviare al server. Esempio: /cmd list")
        return
    try:
        docker_command_args = ["docker", "exec", CONTAINER,
                               "send-command", command_text]
        logging.info(
            f"Esecuzione comando server: {' '.join(docker_command_args)}")
        await run_docker_command(docker_command_args, read_output=False, timeout=10)
        await update.message.reply_text(
            f"Comando '{command_text}' inviato al server.\n"
            "L'output del comando (se presente) dovrebbe apparire nei log del server (visibili con /logs)."
        )
    except asyncio.TimeoutError:
        await update.message.reply_text(f"Errore: Timeout eseguendo il comando '{command_text}'.")
    except subprocess.CalledProcessError as e:
        error_message = e.stderr or str(e.output) or str(e)
        logging.error(
            f"Errore CalledProcessError cmd_command: {error_message}")
        await update.message.reply_text(f"Errore eseguendo il comando '{command_text}':\n<pre>{error_message}</pre>", parse_mode=ParseMode.HTML)
    except Exception as e:
        logging.error(f"Errore imprevisto cmd_command: {e}", exc_info=True)
        await update.message.reply_text(f"Errore imprevisto eseguendo '{command_text}':\n{e}")


@auth_required
async def scarica_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ITEMS
    new_items = await asyncio.to_thread(fetch_items)
    if new_items:
        ITEMS = new_items
        await update.message.reply_text(f"Scaricati {len(ITEMS)} item da Minecraft.")
    else:
        await update.message.reply_text("Errore durante lo scaricamento degli item. Controlla i log del bot.")


@auth_required
async def saveloc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    mc_username = users.get(uid, {}).get("minecraft_username")
    if not mc_username:
        context.user_data["awaiting_mc_username"] = True
        await update.message.reply_text("Sembra che il tuo username Minecraft non sia impostato. Inseriscilo ora, poi riprova /saveloc:")
        return

    context.user_data["awaiting_saveloc_name"] = True
    await update.message.reply_text("Inserisci un nome per la posizione che vuoi salvare:")


@auth_required
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not users.get(uid) or not users[uid].get("minecraft_username"):
        context.user_data["awaiting_mc_username"] = True
        await update.message.reply_text("Sembra che il tuo username Minecraft non sia impostato. Inseriscilo ora:")
        return

    kb = [
        [InlineKeyboardButton("🎁 Give item", callback_data="give")],
        [InlineKeyboardButton("🚀 Teleport", callback_data="tp")],
        [InlineKeyboardButton("☀️ Meteo", callback_data="weather")]
    ]
    await update.message.reply_text("Scegli un'azione:", reply_markup=InlineKeyboardMarkup(kb))

# --- NUOVI COMANDI DIRETTI ---
@auth_required
async def give_direct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not users.get(uid) or not users[uid].get("minecraft_username"):
        context.user_data["awaiting_mc_username"] = True
        await update.message.reply_text("Sembra che il tuo username Minecraft non sia impostato. Inseriscilo ora, poi potrai usare /give:")
        return
    # Simula la pressione del bottone "give"
    context.user_data["awaiting_give_prefix"] = True
    await update.message.reply_text("Ok, inviami il nome (o parte del nome/ID) dell'oggetto che vuoi dare:")

@auth_required
async def tp_direct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    minecraft_username = users.get(uid, {}).get("minecraft_username")
    if not minecraft_username:
        context.user_data["awaiting_mc_username"] = True
        await update.message.reply_text("Sembra che il tuo username Minecraft non sia impostato. Inseriscilo ora, poi potrai usare /tp:")
        return

    # Logica copiata e adattata da button_handler, case "tp"
    try:
        online_players = await get_online_players()
        buttons = []
        if online_players:
            buttons.extend([
                InlineKeyboardButton(p, callback_data=f"tp_player:{p}")
                for p in online_players
            ])
        buttons.append(InlineKeyboardButton("📍 Inserisci coordinate", callback_data="tp_coords"))
        locs = users.get(uid, {}).get("locations", {})
        for name, coords in locs.items():
            buttons.append(
                InlineKeyboardButton(f"📌 {name}", callback_data=f"tp_saved:{name}")
            )
        keyboard_layout = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
        markup = InlineKeyboardMarkup(keyboard_layout)

        text_reply = ""
        if not online_players and not CONTAINER:
            text_reply = ("Impossibile ottenere la lista giocatori "
                          "(CONTAINER non settato o server non raggiungibile).\n"
                          "Puoi usare le posizioni salvate o inserire coordinate manualmente.")
        elif not online_players:
            text_reply = ("Nessun giocatore online trovato.\n"
                          "Puoi usare le posizioni salvate o inserire coordinate manualmente:")
        else:
            text_reply = ("Scegli un giocatore a cui teleportarti, usa una posizione salvata "
                          "o inserisci coordinate:")
        
        await update.message.reply_text(text_reply, reply_markup=markup)

    except Exception as e:
        logging.error(f"Errore in /tp command: {e}", exc_info=True)
        await update.message.reply_text("Si è verificato un errore durante la preparazione del menu di teletrasporto.")


@auth_required
async def weather_direct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not users.get(uid) or not users[uid].get("minecraft_username"):
        context.user_data["awaiting_mc_username"] = True
        await update.message.reply_text("Sembra che il tuo username Minecraft non sia impostato. Inseriscilo ora, poi potrai usare /weather:")
        return
    
    # Logica copiata e adattata da button_handler, case "weather"
    buttons = [
        [InlineKeyboardButton(
            "☀️ Sereno (Clear)", callback_data="weather_set:clear")],
        [InlineKeyboardButton("🌧 Pioggia (Rain)",
                              callback_data="weather_set:rain")],
        [InlineKeyboardButton(
            "⛈ Temporale (Thunder)", callback_data="weather_set:thunder")]
    ]
    await update.message.reply_text("Scegli le condizioni meteo:", reply_markup=InlineKeyboardMarkup(buttons))

# --- FINE NUOVI COMANDI DIRETTI ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()

    if not is_authenticated(uid):
        await update.message.reply_text("Devi prima effettuare il /login.")
        return

    mc_user_details = users.get(uid)
    if not mc_user_details:
        await update.message.reply_text("Errore: utente non trovato. Prova a fare /logout e /login.")
        return

    if context.user_data.get("awaiting_mc_username"):
        users[uid]["minecraft_username"] = text
        save_users()
        context.user_data["awaiting_mc_username"] = False
        await update.message.reply_text(f"Username Minecraft '{text}' salvato.")
        # Non mostrare il menu automaticamente qui, l'utente potrebbe aver inserito l'username
        # a seguito di un comando diretto (es. /give)
        await update.message.reply_text("Ora puoi usare i comandi che richiedono l'username (es. /menu, /give, /tp).")
        return

    minecraft_username = mc_user_details.get("minecraft_username")
    if not minecraft_username: # Dovrebbe essere già gestito sopra, ma per sicurezza
        context.user_data["awaiting_mc_username"] = True
        await update.message.reply_text("Per favore, inserisci prima il tuo username Minecraft:")
        return

    if context.user_data.get("awaiting_username_edit"):
        new_name = update.message.text.strip()
        users[uid]["minecraft_username"] = new_name
        save_users()
        context.user_data.pop("awaiting_username_edit")
        await update.message.reply_text(f"Username aggiornato: {new_name}")
        return

    if context.user_data.get("awaiting_saveloc_name"):
        location_name = update.message.text.strip()
        context.user_data.pop("awaiting_saveloc_name")

        # minecraft_username è già verificato e disponibile qui
        docker_cmd = [
            "docker", "exec", CONTAINER,
            "send-command",
            f"execute as {minecraft_username} at @s run tp @s ~ ~ ~0.0001"
        ]
        try:
            await run_docker_command(docker_cmd, read_output=False, timeout=10)
            await asyncio.sleep(1.0)
            log_args = ["docker", "logs", "--tail", "100", CONTAINER]
            output = await run_docker_command(log_args, read_output=True, timeout=5)

            pattern = rf"Teleported {re.escape(minecraft_username)} to ([0-9\.\-]+),\s*([0-9\.\-]+),\s*([0-9\.\-]+)"
            matches = re.findall(pattern, output)
            if not matches:
                await update.message.reply_text("Impossibile trovare le coordinate nei log. Assicurati di essere in gioco e che i comandi siano abilitati. Riprova più tardi.")
                return
            x, y, z = matches[-1]

            users.setdefault(uid, {}).setdefault("locations", {})[location_name] = {
                "x": float(x), "y": float(y), "z": float(z)
            }
            save_users()
            await update.message.reply_text(f"✅ Posizione '{location_name}' salvata: X={x}, Y={y}, Z={z}")
        except asyncio.TimeoutError:
             await update.message.reply_text("Timeout durante il salvataggio della posizione. Riprova.")
        except subprocess.CalledProcessError as e:
            await update.message.reply_text(f"Errore del server Minecraft durante il salvataggio: {e.stderr or e.output or e}. Potrebbe essere necessario abilitare i comandi o verificare l'username.")
        except Exception as e:
            logging.error(f"Errore in /saveloc (esecuzione comando): {e}", exc_info=True)
            await update.message.reply_text("Si è verificato un errore salvando la posizione.")
        return

    state_handled = False
    if context.user_data.get("awaiting_give_prefix"):
        prefix = text.lower()
        matches = [i for i in ITEMS if i["id"].lower().startswith(
            prefix) or i["name"].lower().startswith(prefix)]
        if not matches:
            await update.message.reply_text("Nessun item trovato con quel prefisso. Riprova, usa /menu o /give.")
        else:
            buttons = [
                InlineKeyboardButton(
                    f'{i["name"]} ({i["id"]})', callback_data=f'give_item:{i["id"]}')
                for i in matches[:10]
            ]
            keyboard = [buttons[j:j+1]
                        for j in range(len(buttons))]
            await update.message.reply_text("Scegli un item:", reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data["awaiting_give_prefix"] = False
        state_handled = True

    elif context.user_data.get("awaiting_item_quantity"):
        if not CONTAINER:
            await update.message.reply_text("Errore: CONTAINER non configurato per il comando give.")
            state_handled = True
            return

        try:
            quantity = int(text)
            if quantity <= 0:
                raise ValueError("La quantità deve essere positiva.")
            item_id = context.user_data.get("selected_item")
            if not item_id:
                await update.message.reply_text("Errore interno: item non selezionato. Riprova da /menu o /give.")
                context.user_data.pop(
                    "awaiting_item_quantity", None)
                return

            cmd_text = f"give {minecraft_username} {item_id} {quantity}"
            docker_cmd_args = ["docker", "exec",
                               CONTAINER, "send-command", cmd_text]
            await run_docker_command(docker_cmd_args, read_output=False)
            await update.message.reply_text(f"Comando eseguito: /give {minecraft_username} {item_id} {quantity}")
        except ValueError:
            await update.message.reply_text("Inserisci un numero valido (intero, maggiore di zero) per la quantità.")
        except asyncio.TimeoutError:
            await update.message.reply_text(f"Timeout eseguendo il comando give.")
        except subprocess.CalledProcessError as e:
            await update.message.reply_text(f"Errore dal server Minecraft: {e.stderr or e.output or e}")
        except Exception as e:
            await update.message.reply_text(f"Errore imprevisto: {e}")
        finally:
            context.user_data.pop("selected_item", None)
            context.user_data.pop("awaiting_item_quantity", None)
        state_handled = True

    elif context.user_data.get("awaiting_tp_coords"):
        if not CONTAINER:
            await update.message.reply_text("Errore: CONTAINER non configurato per il comando teleport.")
            state_handled = True
            return

        parts = text.split()
        if len(parts) != 3:
            await update.message.reply_text("Formato coordinate non valido. Usa: x y z (es. 100 64 -200). Riprova o /menu, /tp.")
        else:
            try:
                x, y, z = map(float, parts)
                cmd_text = f"tp {minecraft_username} {x} {y} {z}"
                docker_cmd_args = ["docker", "exec",
                                   CONTAINER, "send-command", cmd_text]
                await run_docker_command(docker_cmd_args, read_output=False)
                await update.message.reply_text(f"Comando eseguito: /tp {minecraft_username} {x} {y} {z}")
            except ValueError:
                await update.message.reply_text("Le coordinate devono essere numeri validi (es. 100 64.5 -200). Riprova o /menu, /tp.")
            except asyncio.TimeoutError:
                await update.message.reply_text(f"Timeout eseguendo il comando teleport.")
            except subprocess.CalledProcessError as e:
                await update.message.reply_text(f"Errore dal server Minecraft: {e.stderr or e.output or e}")
            except Exception as e:
                await update.message.reply_text(f"Errore imprevisto: {e}")
            finally:
                context.user_data.pop("awaiting_tp_coords", None)
        state_handled = True

    if not state_handled and text and not text.startswith('/'):
        await update.message.reply_text("Comando testuale non riconosciuto. Usa /menu per vedere le opzioni disponibili o /help per la lista comandi.")


async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip().lower()
    if not query:
        await update.inline_query.answer([], cache_time=10)
        return

    matches = [i for i in ITEMS if query in i["id"].lower()
               or query in i["name"].lower()]
    results = [
        InlineQueryResultArticle(
            id=str(uuid.uuid4()),
            title=f'{i["name"]}',
            description=f'ID: {i["id"]}',
            input_message_content=InputTextMessageContent(
                f'/give {{USERNAME}} {i["id"]} 1')
        )
        for i in matches[:20]
    ]
    await update.inline_query.answer(results, cache_time=60)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    if not is_authenticated(uid) or not users.get(uid) or not users[uid].get("minecraft_username"):
        await query.edit_message_text("Errore: autenticazione o username Minecraft mancanti. Prova con /login e imposta l'username.")
        return
    minecraft_username = users[uid]["minecraft_username"]
    data = query.data

    # Controllo CONTAINER per azioni che lo richiedono esplicitamente
    actions_requiring_container = [
        "give_item:", "tp_player:", "tp_coords", "weather_set:",
        "tp_saved:" # Anche teleport su loc salvata richiede container
    ]
    if not CONTAINER and any(data.startswith(action_prefix) for action_prefix in actions_requiring_container):
        await query.edit_message_text("Errore: La variabile CONTAINER non è impostata nel bot. Impossibile eseguire questa azione.")
        return
    # Per "give", "tp", "weather" (i pulsanti iniziali), il controllo container non è strettamente necessario qui
    # perché le funzioni dirette e il menu stesso possono funzionare parzialmente o informare l'utente.
    # Il controllo più stringente avviene quando si tenta di eseguire il comando docker.

    try:
        if data == "edit_username":
            context.user_data["awaiting_username_edit"] = True
            await query.edit_message_text("Inserisci il nuovo username Minecraft:")

        elif data == "delete_location":
            locs = users.get(uid, {}).get("locations", {})
            if not locs:
                await query.edit_message_text("Non hai posizioni salvate.")
                return
            buttons = [
                [InlineKeyboardButton(f"❌ {name}", callback_data=f"delete_loc:{name}")]
                for name in locs
            ]
            await query.edit_message_text(
                "Seleziona la posizione da cancellare:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )

        elif data.startswith("delete_loc:"):
            name = data.split(":", 1)[1]
            if name in users[uid].get("locations", {}):
                users[uid]["locations"].pop(name)
                save_users()
                await query.edit_message_text(f"Posizione «{name}» cancellata 🔥")
            else:
                await query.edit_message_text(f"Posizione «{name}» non trovata.")

        elif data == "give": # Bottone dal /menu
            context.user_data["awaiting_give_prefix"] = True
            await query.edit_message_text("Ok, inviami il nome (o parte del nome/ID) dell'oggetto che vuoi dare:")
        
        elif data.startswith("give_item:"):
            item_id = data.split(":", 1)[1]
            context.user_data["selected_item"] = item_id
            context.user_data["awaiting_item_quantity"] = True
            await query.edit_message_text(f"Item selezionato: {item_id}.\nInserisci la quantità desiderata:")
        
        elif data == "tp": # Bottone dal /menu
            online_players = await get_online_players()
            buttons = []
            if online_players:
                buttons.extend([
                    InlineKeyboardButton(p, callback_data=f"tp_player:{p}")
                    for p in online_players
                ])
            buttons.append(InlineKeyboardButton("📍 Inserisci coordinate", callback_data="tp_coords"))
            locs = users.get(uid, {}).get("locations", {})
            for name, coords in locs.items():
                buttons.append(
                    InlineKeyboardButton(f"📌 {name}", callback_data=f"tp_saved:{name}")
                )
            keyboard_layout = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
            markup = InlineKeyboardMarkup(keyboard_layout)
            
            text_reply = ""
            if not online_players and not CONTAINER:
                text_reply = ("Impossibile ottenere la lista giocatori "
                              "(CONTAINER non settato o server non raggiungibile).\n"
                              "Puoi usare le posizioni salvate o inserire coordinate manualmente.")
            elif not online_players:
                text_reply = ("Nessun giocatore online trovato.\n"
                              "Puoi usare le posizioni salvate o inserire coordinate manualmente:")
            else:
                text_reply = ("Scegli un giocatore a cui teleportarti, usa una posizione salvata "
                              "o inserisci coordinate:")
            await query.edit_message_text(text_reply, reply_markup=markup)

        elif data.startswith("tp_saved:"):
            if not CONTAINER: # Controllo specifico prima dell'azione
                await query.edit_message_text("Errore: CONTAINER non configurato per il comando teleport.")
                return
            location_name = data.split(":", 1)[1]
            loc = users[uid]["locations"].get(location_name)
            if not loc:
                await query.edit_message_text(f"Posizione '{location_name}' non trovata.")
                return
            x, y, z = loc["x"], loc["y"], loc["z"]
            cmd = f"tp {minecraft_username} {x} {y} {z}"
            docker_args = ["docker", "exec", CONTAINER, "send-command", cmd]
            await run_docker_command(docker_args, read_output=False)
            await query.edit_message_text(f"Teleport eseguito su '{location_name}': {x}, {y}, {z}")

        elif data == "tp_coords":
            context.user_data["awaiting_tp_coords"] = True
            await query.edit_message_text("Inserisci le coordinate nel formato: `x y z` (es. `100 64 -200`)")
        
        elif data.startswith("tp_player:"):
            if not CONTAINER: # Controllo specifico prima dell'azione
                await query.edit_message_text("Errore: CONTAINER non configurato per il comando teleport.")
                return
            target_player = data.split(":", 1)[1]
            cmd_text = f"tp {minecraft_username} {target_player}"
            docker_cmd_args = ["docker", "exec",
                               CONTAINER, "send-command", cmd_text]
            await run_docker_command(docker_cmd_args, read_output=False)
            await query.edit_message_text(f"Teleport verso {target_player} eseguito!")
        
        elif data == "weather": # Bottone dal /menu
            buttons = [
                [InlineKeyboardButton(
                    "☀️ Sereno (Clear)", callback_data="weather_set:clear")],
                [InlineKeyboardButton("🌧 Pioggia (Rain)",
                                      callback_data="weather_set:rain")],
                [InlineKeyboardButton(
                    "⛈ Temporale (Thunder)", callback_data="weather_set:thunder")]
            ]
            await query.edit_message_text("Scegli le condizioni meteo:", reply_markup=InlineKeyboardMarkup(buttons))
        
        elif data.startswith("weather_set:"):
            if not CONTAINER: # Controllo specifico prima dell'azione
                await query.edit_message_text("Errore: CONTAINER non configurato per il comando weather.")
                return
            weather_condition = data.split(":", 1)[1]
            cmd_text = f"weather {weather_condition}"
            docker_cmd_args = ["docker", "exec",
                               CONTAINER, "send-command", cmd_text]
            await run_docker_command(docker_cmd_args, read_output=False)
            await query.edit_message_text(f"Meteo impostato su: {weather_condition.capitalize()}")
        else:
            await query.edit_message_text("Azione non riconosciuta o scaduta.")

    except asyncio.TimeoutError:
        await query.edit_message_text(f"Timeout eseguendo l'azione richiesta. Riprova.")
    except subprocess.CalledProcessError as e:
        error_detail = e.stderr or e.output or str(e)
        await query.edit_message_text(f"Errore dal server Minecraft: {error_detail}. Riprova o contatta un admin.")
        logging.error(
            f"CalledProcessError in button_handler for data '{data}': {error_detail}")
    except Exception as e:
        logging.error(
            f"Errore imprevisto in button_handler for data '{data}': {e}", exc_info=True)
        await query.edit_message_text("Si è verificato un errore imprevisto. Riprova più tardi.")


# --- Main ---
def main():
    if not TOKEN:
        logging.critical(
            "TELEGRAM_TOKEN non impostato. Il bot non può partire.")
        return
    if not CONTAINER:
        logging.warning(
            "La variabile CONTAINER non è impostata (nome container Docker). Funzionalità server Minecraft limitate.")

    app = ApplicationBuilder().token(TOKEN).build()

    # Comandi
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("logs", logs_command))
    app.add_handler(CommandHandler("scarica_items", scarica_items))
    app.add_handler(CommandHandler("cmd", cmd_command))
    app.add_handler(CommandHandler("saveloc", saveloc_command))
    app.add_handler(CommandHandler("edituser", edituser))

    # NUOVI COMANDI DIRETTI REGISTRATI
    app.add_handler(CommandHandler("give", give_direct_command))
    app.add_handler(CommandHandler("tp", tp_direct_command))
    app.add_handler(CommandHandler("weather", weather_direct_command))

    # Gestori di messaggi e callback
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(InlineQueryHandler(inline_query_handler))

    logging.info("Bot avviato e in attesa di comandi...")
    app.run_polling()


if __name__ == "__main__":
    main()