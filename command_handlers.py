# minecraft_telegram_bot/command_handlers.py
# This file now serves as a central point for importing command handlers
# from their respective, more organized files.

from .auth_handlers import start, help_command, login, logout, edituser
from .server_handlers import logs_command, cmd_command, stop_server_command, start_server_command, restart_server_command
from .world_handlers import backup_world_command, list_backups_command, imnotcreative_command
from .quick_action_handlers import menu_command, give_direct_command, tp_direct_command, weather_direct_command
from .item_handlers import scarica_items_command
from .location_handlers import saveloc_command
from .resource_pack_handlers import add_resourcepack_command, edit_resourcepacks_command
from .structure_handlers import handle_split_mcstructure, handle_convert2mc, handle_structura_cli

# You might still need some imports here if they are used by multiple handler files
# or for registration in bot.py, but ideally, move imports to the specific handler files.
# from telegram.ext import ContextTypes # Example: if a function in this file needed it

# Any functions that don't fit into the new categories or are helper functions
# used across multiple categories could potentially remain here, but it's
# generally better to place them in the most relevant new file or a dedicated
# utility file if truly general.

# Based on the original file, it seems all command handlers have been moved.
# This file will now mainly contain imports and potentially the list of handlers
# to be added to the dispatcher in bot.py (though that logic might also be better
# placed directly in bot.py or a dedicated handler registration module).

# For now, we'll keep it simple with just imports.
