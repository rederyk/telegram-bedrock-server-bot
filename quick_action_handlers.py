# minecraft_telegram_bot/quick_action_handlers.py
import html

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import get_logger
from user_management import auth_required, get_minecraft_username, get_locations
from docker_utils import get_online_players_from_server

logger = get_logger(__name__)

@auth_required
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not get_minecraft_username(update.effective_user.id): # type: ignore
        context.user_data["awaiting_mc_username"] = True # type: ignore
        context.user_data["next_action_after_username"] = "menu" # type: ignore
        await update.message.reply_text("👤 Inserisci il tuo username Minecraft:")
        return
    await update.message.reply_text("🎒 Scegli un'azione:", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 Give", callback_data="menu_give")],
        [InlineKeyboardButton("🚀 Teleport", callback_data="menu_tp")],
        [InlineKeyboardButton("☀️ Meteo", callback_data="menu_weather")]
    ]))

@auth_required
async def give_direct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not get_minecraft_username(update.effective_user.id): # type: ignore
        context.user_data["awaiting_mc_username"] = True # type: ignore
        context.user_data["next_action_after_username"] = "give" # type: ignore
        await update.message.reply_text("👤 Inserisci il tuo username Minecraft:")
        return
    context.user_data["awaiting_give_prefix"] = True # type: ignore
    await update.message.reply_text("🎁 Nome o ID dell'oggetto da dare:")

@auth_required
async def tp_direct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id # type: ignore
    if not get_minecraft_username(uid): # type: ignore
        context.user_data["awaiting_mc_username"] = True # type: ignore
        context.user_data["next_action_after_username"] = "tp" # type: ignore
        await update.message.reply_text("👤 Inserisci il tuo username Minecraft:")
        return
    try:
        online_players = await get_online_players_from_server()
        buttons = []
        if online_players:
            buttons.extend([InlineKeyboardButton(p, callback_data=f"tp_player:{p}") for p in online_players])
        buttons.append(InlineKeyboardButton("📍 Inserisci coordinate", callback_data="tp_coords_input"))
        user_locs = get_locations(uid) # type: ignore
        for name_loc in user_locs:
            buttons.append(InlineKeyboardButton(f"📌 {name_loc}", callback_data=f"tp_saved:{name_loc}"))

        if not buttons:
            await update.message.reply_text("Nessuna opzione di teletrasporto rapido disponibile.")
            return

        keyboard_layout = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
        markup = InlineKeyboardMarkup(keyboard_layout)
        await update.message.reply_text("🚀 Scegli destinazione teletrasporto:", reply_markup=markup)

    except Exception as e:
        logger.error(f"🚀❌ Errore /tp: {e}", exc_info=True)
        await update.message.reply_text("❌ Errore preparando opzioni di teletrasporto.")

@auth_required
async def weather_direct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not get_minecraft_username(update.effective_user.id): # type: ignore
        context.user_data["awaiting_mc_username"] = True # type: ignore
        context.user_data["next_action_after_username"] = "weather" # type: ignore
        await update.message.reply_text("👤 Inserisci il tuo username Minecraft:")
        return
    await update.message.reply_text("☀️ Scegli il meteo:", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("☀️ Sereno", callback_data="weather_set:clear")],
        [InlineKeyboardButton("🌧 Pioggia", callback_data="weather_set:rain")],
        [InlineKeyboardButton("⛈ Temporale", callback_data="weather_set:thunder")]
    ]))
