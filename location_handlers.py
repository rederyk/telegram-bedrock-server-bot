# minecraft_telegram_bot/location_handlers.py
from telegram import Update
from telegram.ext import ContextTypes

from config import get_logger
from user_management import auth_required, get_minecraft_username

logger = get_logger(__name__)

@auth_required
async def saveloc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id # type: ignore
    if not get_minecraft_username(uid): # type: ignore
        context.user_data["awaiting_mc_username"] = True # type: ignore
        context.user_data["next_action_after_username"] = "saveloc" # type: ignore
        await update.message.reply_text("👤 Inserisci il tuo username Minecraft:")
        return
    context.user_data["awaiting_saveloc_name"] = True # type: ignore
    await update.message.reply_text("📍 Nome per la posizione da salvare:")
