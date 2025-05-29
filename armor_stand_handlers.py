# minecraft_telegram_bot/armor_stand_handlers.py
import asyncio
import html
import re

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import CONTAINER, get_logger
from user_management import auth_required, get_minecraft_username
from docker_utils import run_docker_command
from hologram_handlers import execute_hologram_paste, cleanup_hologram_data # Assuming these are needed here

logger = get_logger(__name__)

def calculate_distance_3d(pos1: dict, pos2: dict) -> float:
    """Calcola distanza 3D tra due posizioni"""
    return ((pos1['x'] - pos2['x'])**2 + (pos1['y'] - pos2['y'])**2 + (pos1['z'] - pos2['z'])**2)**0.5


# Versione per hologram
async def detect_armor_stand_for_hologram_improved_mh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Versione per paste hologram - Entry point dal comando /pasteHologram
    """
    uid = update.effective_user.id
    minecraft_username = get_minecraft_username(uid)

    if not minecraft_username:
        context.user_data["awaiting_mc_username"] = True
        context.user_data["next_action_data"] = {"type": "paste_hologram", "update": update}
        await update.message.reply_text("👤 Inserisci il tuo username Minecraft:")
        return

    if not CONTAINER:
        await update.message.reply_text("⚠️ CONTAINER non impostato.")
        return

    # Check if a structure file has been uploaded
    structure_path = context.user_data.get("hologram_structure_path")
    if not structure_path or not os.path.exists(structure_path):
         await update.message.reply_text(
             "📁 Nessun file struttura (.mcstructure) caricato per il paste hologram.\n"
             "Per favore, carica prima il file struttura."
         )
         # Optionally set a state to await document upload
         context.user_data["awaiting_hologram_structure"] = True
         return


    await update.message.reply_text("🔍 **Rilevamento Armor Stand**\nAvvio ricerca armor stand per Paste Hologram...")

    try:
        # Use the improved detection logic from hologram_handlers
        from hologram_handlers import detect_armor_stand_for_hologram_improved
        await detect_armor_stand_for_hologram_improved(update, context, minecraft_username)

    except Exception as e:
        logger.error(f"🔍❌ Errore rilevamento armor stand per hologram: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Errore durante il rilevamento: {html.escape(str(e))}")
        from hologram_handlers import cleanup_hologram_data
        cleanup_hologram_data(context)
