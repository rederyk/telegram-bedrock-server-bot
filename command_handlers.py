# minecraft_telegram_bot/command_handlers.py
import asyncio
import subprocess
import re # re è usato in saveloc, che è stato spostato in message_handlers
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import CONTAINER, get_logger
from user_management import (
    auth_required, authenticate_user, logout_user,
    get_minecraft_username, set_minecraft_username,
    get_user_data, get_locations
)
from item_management import refresh_items, get_items
from docker_utils import run_docker_command, get_online_players_from_server

logger = get_logger(__name__)

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
    if get_minecraft_username(uid) and get_user_data(uid): # Già autenticato e con username
        await update.message.reply_text("Sei già autenticato e il tuo username è impostato.")
        return
    if not args:
        await update.message.reply_text("Per favore, fornisci la password. Es: /login MIA_PASSWORD")
        return

    password_attempt = args[0]
    if authenticate_user(uid, password_attempt):
        await update.message.reply_text("Autenticazione avvenuta con successo!")
        if not get_minecraft_username(uid):
            context.user_data["awaiting_mc_username"] = True # Stato per handle_message
            await update.message.reply_text(
                "Per favore, inserisci ora il tuo nome utente Minecraft:"
            )
        else:
            await update.message.reply_text(f"Bentornato! Username Minecraft: {get_minecraft_username(uid)}")
    else:
        await update.message.reply_text("Password errata.")


@auth_required
async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logout_user(update.effective_user.id)
    await update.message.reply_text("Logout eseguito.")

@auth_required
async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CONTAINER:
        await update.message.reply_text("Variabile CONTAINER non impostata. Impossibile recuperare i log.")
        return
    try:
        command_args = ["docker", "logs", "--tail", "50", CONTAINER]
        # Non passiamo CONTAINER a run_docker_command qui perché è già parte di command_args
        output = await run_docker_command(command_args, read_output=True, timeout=10)
        output = output or "(Nessun output dai log)"
        safe_output = output.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        msg = f"<b>Ultimi 50 log del server ({CONTAINER}):</b>\n<pre>{safe_output[:3900]}</pre>"
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except asyncio.TimeoutError:
        await update.message.reply_text("Errore: Timeout durante il recupero dei log.")
    except subprocess.CalledProcessError as e:
        await update.message.reply_text(f"Errore nel comando Docker per i log: {e.stderr or e.output or e}")
    except ValueError as e: # Per CONTAINER non configurato
        await update.message.reply_text(str(e))
    except Exception as e:
        logger.error(f"Errore imprevisto logs_command: {e}", exc_info=True)
        await update.message.reply_text(f"Errore imprevisto recuperando i log: {e}")

@auth_required
async def edituser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("✏️ Modifica username", callback_data="edit_username")],
        [InlineKeyboardButton("🗑️ Cancella posizione salvata", callback_data="delete_location")],
    ]
    await update.message.reply_text("Cosa vuoi fare?", reply_markup=InlineKeyboardMarkup(kb))

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
        docker_command_args = ["docker", "exec", CONTAINER, "send-command", command_text]
        logger.info(f"Esecuzione comando server: {' '.join(docker_command_args)}")
        await run_docker_command(docker_command_args, read_output=False, timeout=10)
        await update.message.reply_text(
            f"Comando '{command_text}' inviato al server.\n"
            "L'output del comando (se presente) dovrebbe apparire nei log del server (visibili con /logs)."
        )
    except asyncio.TimeoutError:
        await update.message.reply_text(f"Errore: Timeout eseguendo il comando '{command_text}'.")
    except subprocess.CalledProcessError as e:
        error_message = e.stderr or str(e.output) or str(e)
        logger.error(f"Errore CalledProcessError cmd_command: {error_message}")
        await update.message.reply_text(
            f"Errore eseguendo il comando '{command_text}':\n<pre>{error_message}</pre>",
            parse_mode=ParseMode.HTML
        )
    except ValueError as e: # Per CONTAINER non configurato
        await update.message.reply_text(str(e))
    except Exception as e:
        logger.error(f"Errore imprevisto cmd_command: {e}", exc_info=True)
        await update.message.reply_text(f"Errore imprevisto eseguendo '{command_text}':\n{e}")


@auth_required
async def scarica_items_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Avvio aggiornamento lista item...")
    # Esegui l'operazione in un thread separato per non bloccare il loop asyncio
    updated_items = await asyncio.to_thread(refresh_items)
    if updated_items:
        await update.message.reply_text(f"Scaricati {len(updated_items)} item da Minecraft.")
    else:
        # Controlla se ITEMS ha comunque qualcosa (dal file, per esempio)
        current_items = get_items()
        if current_items:
            await update.message.reply_text(
                f"Errore durante lo scaricamento degli item. Utilizzo la lista precedentemente caricata ({len(current_items)} item). "
                "Controlla i log del bot per dettagli sull'errore di download."
            )
        else:
            await update.message.reply_text(
                "Errore critico: impossibile scaricare o caricare la lista degli item. "
                "La funzionalità di give potrebbe non funzionare. Controlla i log del bot."
            )

@auth_required
async def saveloc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    mc_username = get_minecraft_username(uid)
    if not mc_username:
        context.user_data["awaiting_mc_username"] = True
        context.user_data["next_action"] = "saveloc" # Per reindirizzare dopo l'inserimento dell'username
        await update.message.reply_text(
            "Sembra che il tuo username Minecraft non sia impostato. "
            "Inseriscilo ora, poi riprova /saveloc:"
        )
        return

    context.user_data["awaiting_saveloc_name"] = True # Stato per handle_message
    await update.message.reply_text("Inserisci un nome per la posizione che vuoi salvare:")


@auth_required
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not get_minecraft_username(uid):
        context.user_data["awaiting_mc_username"] = True
        context.user_data["next_action"] = "menu" # Per reindirizzare dopo l'inserimento dell'username
        await update.message.reply_text(
            "Sembra che il tuo username Minecraft non sia impostato. Inseriscilo ora:"
        )
        return

    kb = [
        [InlineKeyboardButton("🎁 Give item", callback_data="menu_give")],
        [InlineKeyboardButton("🚀 Teleport", callback_data="menu_tp")],
        [InlineKeyboardButton("☀️ Meteo", callback_data="menu_weather")]
    ]
    await update.message.reply_text("Scegli un'azione:", reply_markup=InlineKeyboardMarkup(kb))


# --- COMANDI DIRETTI ---
@auth_required
async def give_direct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not get_minecraft_username(uid):
        context.user_data["awaiting_mc_username"] = True
        context.user_data["next_action"] = "give" # Per reindirizzare
        await update.message.reply_text(
            "Sembra che il tuo username Minecraft non sia impostato. "
            "Inseriscilo ora, poi potrai usare /give:"
        )
        return
    context.user_data["awaiting_give_prefix"] = True # Stato per handle_message
    await update.message.reply_text(
        "Ok, inviami il nome (o parte del nome/ID) dell'oggetto che vuoi dare:"
    )

@auth_required
async def tp_direct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    minecraft_username = get_minecraft_username(uid)
    if not minecraft_username:
        context.user_data["awaiting_mc_username"] = True
        context.user_data["next_action"] = "tp" # Per reindirizzare
        await update.message.reply_text(
            "Sembra che il tuo username Minecraft non sia impostato. "
            "Inseriscilo ora, poi potrai usare /tp:"
        )
        return

    try:
        online_players = await get_online_players_from_server()
        buttons = []
        if online_players:
            buttons.extend([
                InlineKeyboardButton(p, callback_data=f"tp_player:{p}")
                for p in online_players
            ])
        buttons.append(InlineKeyboardButton("📍 Inserisci coordinate", callback_data="tp_coords_input"))

        user_locs = get_locations(uid)
        for name in user_locs:
            buttons.append(InlineKeyboardButton(f"📌 {name}", callback_data=f"tp_saved:{name}"))

        keyboard_layout = [buttons[i:i+2] for i in range(0, len(buttons), 2)] # Max 2 bottoni per riga
        markup = InlineKeyboardMarkup(keyboard_layout)

        text_reply = "Scegli una destinazione per il teletrasporto:"
        if not online_players and not CONTAINER:
            text_reply = (
                "Impossibile ottenere la lista giocatori (CONTAINER non settato o server non raggiungibile).\n"
                "Puoi usare le posizioni salvate o inserire coordinate manualmente."
            )
        elif not online_players:
            text_reply = (
                "Nessun giocatore online trovato.\n"
                "Puoi usare le posizioni salvate o inserire coordinate manualmente:"
            )
        await update.message.reply_text(text_reply, reply_markup=markup)

    except ValueError as e: # Per CONTAINER non configurato
        await update.message.reply_text(str(e))
    except Exception as e:
        logger.error(f"Errore in /tp command: {e}", exc_info=True)
        await update.message.reply_text(
            "Si è verificato un errore durante la preparazione del menu di teletrasporto."
        )


@auth_required
async def weather_direct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not get_minecraft_username(uid):
        context.user_data["awaiting_mc_username"] = True
        context.user_data["next_action"] = "weather" # Per reindirizzare
        await update.message.reply_text(
            "Sembra che il tuo username Minecraft non sia impostato. "
            "Inseriscilo ora, poi potrai usare /weather:"
        )
        return

    buttons = [
        [InlineKeyboardButton("☀️ Sereno (Clear)", callback_data="weather_set:clear")],
        [InlineKeyboardButton("🌧 Pioggia (Rain)", callback_data="weather_set:rain")],
        [InlineKeyboardButton("⛈ Temporale (Thunder)", callback_data="weather_set:thunder")]
    ]
    await update.message.reply_text(
        "Scegli le condizioni meteo:", reply_markup=InlineKeyboardMarkup(buttons)
    )