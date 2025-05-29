# minecraft_telegram_bot/message_handlers.py
import asyncio # Still needed for run_docker_command timeout
import subprocess # Still needed for run_docker_command
import html # Still needed for error messages

from telegram import Update
from telegram.ext import ContextTypes

from config import get_logger, WORLD_NAME # Still needed
from user_management import is_user_authenticated # Still needed
from docker_utils import run_docker_command # Still needed

# Import handlers from new files
from user_input_handlers import (
    handle_username_input, handle_username_edit_input, handle_saveloc_name_input,
    handle_give_prefix_input, handle_item_quantity_input, handle_rp_new_position_input,
    handle_tp_coords_input, handle_hologram_paste_confirmation # Import the new handler
)
from callback_handlers import callback_query_handler
from document_handlers import handle_document_message
from inline_handlers import inline_query_handler


logger = get_logger(__name__)

# Keep necessary global variables if they are still used in this file or imported elsewhere
# PYTHON_AMULET, PYTHON_STRUCTURA, SPLIT_SCRIPT, CONVERT_SCRIPT, STRUCTURA_SCRIPT, STRUCTURA_DIR, SPLIT_THRESHOLD
# These seem related to the wizard and paste hologram, which are now in separate files.
# Let's remove them from here unless they are proven to be needed.

# Keep WORLD_NAME and CONTAINER as they are imported from config and used in user_input_handlers
# Keep logger as it's used here.


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()

    if not is_user_authenticated(uid):
        await update.message.reply_text("Devi prima effettuare il /login.")
        return

    # Delegate to user_input_handlers based on state

    # Check for hologram paste confirmation first
    if await handle_hologram_paste_confirmation(update, context, text):
        return

    if context.user_data.get("awaiting_structura_opacity"):
        # This state is handled by structure_wizard_handlers, but the input comes here.
        # Need to import the handler from structure_wizard_handlers.
        from structure_wizard_handlers import handle_structura_opacity_input
        await handle_structura_opacity_input(update, context, int(text)) # Assuming text is always int here after validation
        return

    if context.user_data.get("awaiting_mc_username"):
        await handle_username_input(update, context, text)
        return

    if context.user_data.get("awaiting_username_edit"):
        await handle_username_edit_input(update, context, text)
        return

    if context.user_data.get("awaiting_saveloc_name"):
        await handle_saveloc_name_input(update, context, text)
        return

    if context.user_data.get("awaiting_give_prefix"):
        await handle_give_prefix_input(update, context, text)
        return

    if context.user_data.get("awaiting_item_quantity"):
        await handle_item_quantity_input(update, context, text)
        return

    if context.user_data.get("awaiting_rp_new_position"):
        await handle_rp_new_position_input(update, context, text)
        return

    if context.user_data.get("awaiting_tp_coords_input"):
        await handle_tp_coords_input(update, context, text)
        return

    # Default for non-command text if no state is active
    if not text.startswith('/'):
        await update.message.reply_text(
            "Comando testuale non riconosciuto o stato non attivo. "
            "Usa /menu per vedere le opzioni o /help per la lista comandi."
        )

# The callback_query_handler, inline_query_handler, and handle_document_message
# functions are now in their respective files and should be imported and used
# in the main bot file (bot.py) where the handlers are added to the dispatcher.
# They should not be present in this file anymore.

# Remove all other moved functions below this line.
