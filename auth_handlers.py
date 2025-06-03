# minecraft_telegram_bot/auth_handlers.py
import html
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import get_logger
from user_management import (
    auth_required, authenticate_user, logout_user,
    get_minecraft_username, get_user_data
)

logger = get_logger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bot Minecraft attivo. Usa /login <code>password</code> per iniziare."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 <b>Minecraft Bedrock Admin Bot</b>\n\n"

        "🔐 <b>Autenticazione &amp; Utente</b>\n"
        "<b>/login &lt;password&gt;</b> – Accedi al bot\n"
        "<b>/logout</b> – Esci\n"
        "<b>/edituser</b> – Modifica username o elimina posizioni\n\n"

        "🎒 <b>Azioni Veloci</b> (<b>/menu</b>)\n"
        "• <b>/give</b> – Dai un oggetto\n"
        "• <b>/tp</b> – Teletrasportati\n"
        "• <b>/weather</b> – Cambia il meteo\n\n"

        "🎁 <b>Gestione Inventario</b>\n"
        "<b>/give</b> – Seleziona oggetto e quantità\n"
        "  (supporta ricerca inline: digita <code>@nome_bot</code> + oggetto)\n\n"

        "🚀 <b>Teletrasporto</b>\n"
        "<b>/tp</b> – Scegli tra giocatori online, coordinate o posizioni\n\n"

        "☀️ <b>Meteo</b>\n"
        "<b>/weather</b> – Sereno, Pioggia o Temporale\n\n"

        "📍 <b>Salva Posizione</b>\n"
        "<b>/saveloc</b> – Dai un nome alla tua posizione attuale\n\n"

        "⚙️ <b>Comandi Avanzati</b>\n"
        "<b>/cmd comando</b> – Console server (più righe, # commenti)\n"
        "<b>/logs</b> – Ultime 50 righe di log\n\n"

        "💾 <b>Backup &amp; Ripristino</b>\n"
        "<b>/backup_world</b> – Crea backup (.zip), ferma/riprende server\n"
        "<b>/list_backups</b> – Elenca e scarica gli ultimi 15 backup\n\n"

        "🛠️ <b>Server Control</b>\n"
        "<b>/startserver</b> – Avvia container Docker\n"
        "<b>/stopserver</b> – Arresta container Docker\n"
        "<b>/restartserver</b> – Riavvia container Docker\n\n"

        "🎨 <b>Resource Pack</b>\n"
        "<b>/addresourcepack</b> – Invia file .zip/.mcpack\n"
        "<b>/editresourcepacks</b> – Gestisci ordine o elimina pack attivi\n\n"

        "🛠️ <b>Modalità Creativa</b>\n"
        "<b>/imnotcreative</b> – Resetta flag creativo (richiede conferma)\n\n"

        "✨ <b>Utility</b>\n"
        "<b>/scarica_items</b> – Aggiorna lista item per <b>/give</b>\n\n"

        "❓ <b>Altri comandi</b>\n"
        "<b>/start</b> – Messaggio di benvenuto\n"
        "<b>/help</b> – Questa guida veloce\n\n"

        "<i>Per suggerimenti inline</i>: digita <code>@nome_bot</code> + nome/ID oggetto"
    )
    logger.info("Invio help completo")
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)


async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    args = context.args
    if get_user_data(uid): # type: ignore
        # Allow re-authentication
        #await update.message.reply_text("🔑✅ Sei già autenticato e username Minecraft impostato.")
        #return
        pass
    if not args:
        await update.message.reply_text("Per favore, fornisci la password. Es: /login MIA_PASSWORD")
        return
    password_attempt = args[0]
    if authenticate_user(uid, password_attempt):
        await update.message.reply_text("🔑✅ Autenticazione riuscita!")
        if not get_minecraft_username(uid):
            context.user_data["awaiting_mc_username"] = True
            context.user_data["next_action_after_username"] = "post_login_greeting"
            await update.message.reply_text("👤 Inserisci ora il tuo nome utente Minecraft:")
        else:
            await update.message.reply_text(f"Bentornato! Username Minecraft: {get_minecraft_username(uid)}")
    else:
        await update.message.reply_text("🔑❌ Password errata.")
async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logout_user(update.effective_user.id) # type: ignore
    await update.message.reply_text("👋 Logout eseguito.")

async def edituser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup # Import locally to avoid circular dependency if needed elsewhere
    await update.message.reply_text("Cosa vuoi fare?", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Modifica username", callback_data="edit_username")],
        [InlineKeyboardButton("🗑️ Cancella posizione", callback_data="delete_location")]
    ]))
