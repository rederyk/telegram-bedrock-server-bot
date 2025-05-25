import asyncio

from telegram import BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, InlineQueryHandler, filters, ConversationHandler
)

from config import TOKEN, CONTAINER, logger, WORLD_NAME

import command_handlers

from message_handlers import (
    handle_text_message, callback_query_handler, inline_query_handler,
    handle_document_message
)

async def set_bot_commands(application):
    commands = [
        BotCommand("menu", "🎒 Apri azioni rapide"),
        BotCommand("tp", "🚀 Teletrasportati"),
        BotCommand("weather", "☀️ Cambia meteo"),
        BotCommand("give", "🎁 Dai un oggetto"),
        BotCommand("saveloc", "📍 Salva posizione"),
        BotCommand("edituser", "👤 Modifica utente/posizioni"),
        BotCommand("cmd", "⚙️ Esegui comando server"),
        BotCommand("logs", "📄 Vedi log server"),
        BotCommand("backup_world", "💾 Backup mondo"),
        BotCommand("list_backups", "📂 Lista backup"),
        BotCommand("addresourcepack", "📦🖼️ Aggiungi resource pack"),
        BotCommand("editresourcepacks", "📦🛠️ Modifica resource pack"),
        BotCommand("scarica_items", "✨ Aggiorna lista item"),
        BotCommand("logout", "👋 Esci dal bot"),
        BotCommand("login", "🔑 Accedi al bot"),
        BotCommand("startserver", "▶️ Avvia server MC"),
        BotCommand("stopserver", "⏹️ Ferma server MC"),
        BotCommand("restartserver", "🔄 Riavvia server MC"),
        BotCommand("imnotcreative", "🛠️ Resetta flag creativo"),
        BotCommand("split_structure", "✂️ Dividi struttura (.mcstructure/.schematic)"),
        BotCommand("convert_structure", "🔄 Converti .schematic → .mcstructure"),
        BotCommand("create_resourcepack", "📦 Crea resource pack da .mcstructure"),
        BotCommand("help", "❓ Aiuto comandi")
    ]
    try:
        await application.bot.set_my_commands(commands)
        logger.info("✅ Comandi Bot Telegram impostati.")
    except Exception as e:
        logger.error(f"❌ Errore impostazione comandi Bot: {e}", exc_info=True)

def main_sync():
    if not TOKEN:
        logger.critical("🚨 TOKEN Telegram mancante! Il bot non può avviarsi.")
        return
    if not CONTAINER: # Già loggato in config.py ma ribadire non fa male
        logger.warning("⚠️  CONTAINER non impostato in config. Funzionalità server limitate.")
    if not WORLD_NAME: # Già loggato in config.py
        logger.warning("⚠️  WORLD_NAME non impostato in config. Funzionalità mondo (backup, RP) limitate.")


    logger.info("🤖 Inizializzazione Bot Telegram...")
    application = ApplicationBuilder().token(TOKEN).build()

    loop = asyncio.get_event_loop()
    try:
        if loop.is_running():
            logger.info("⚙️ Loop asyncio attivo, creo task per set_bot_commands.")
            loop.create_task(set_bot_commands(application))
        else:
            logger.info("⚙️ Eseguo set_bot_commands in loop asyncio.")
            loop.run_until_complete(set_bot_commands(application))
    except RuntimeError as e:
        logger.error(f"⚙️❌ RuntimeError set_bot_commands in loop: {e}. Provare approccio diverso se in thread async.")
    except Exception as e:
        logger.error(f"🆘 Errore generico set_bot_commands: {e}", exc_info=True)

    application.add_handler(CommandHandler("start", command_handlers.start))
    application.add_handler(CommandHandler("help", command_handlers.help_command))
    application.add_handler(CommandHandler("login", command_handlers.login))
    application.add_handler(CommandHandler("logout", command_handlers.logout))
    application.add_handler(CommandHandler("menu", command_handlers.menu_command))
    application.add_handler(CommandHandler("logs", command_handlers.logs_command))
    application.add_handler(CommandHandler("scarica_items", command_handlers.scarica_items_command))
    application.add_handler(CommandHandler("cmd", command_handlers.cmd_command))
    application.add_handler(CommandHandler("saveloc", command_handlers.saveloc_command))
    application.add_handler(CommandHandler("edituser", command_handlers.edituser))
    application.add_handler(CommandHandler("give", command_handlers.give_direct_command))
    application.add_handler(CommandHandler("tp", command_handlers.tp_direct_command))
    application.add_handler(CommandHandler("weather", command_handlers.weather_direct_command))

    application.add_handler(CommandHandler("startserver", command_handlers.start_server_command))
    application.add_handler(CommandHandler("stopserver", command_handlers.stop_server_command))
    application.add_handler(CommandHandler("restartserver", command_handlers.restart_server_command))
    application.add_handler(CommandHandler("imnotcreative", command_handlers.imnotcreative_command))
    application.add_handler(CommandHandler("backup_world", command_handlers.backup_world_command))
    application.add_handler(CommandHandler("list_backups", command_handlers.list_backups_command))
    application.add_handler(CommandHandler("addresourcepack", command_handlers.add_resourcepack_command))
    application.add_handler(CommandHandler("editresourcepacks", command_handlers.edit_resourcepacks_command))

    application.add_handler(CommandHandler("split_structure", command_handlers.handle_split_mcstructure))
    application.add_handler(CommandHandler("convert_structure", command_handlers.handle_convert2mc))
    application.add_handler(CommandHandler("create_resourcepack", command_handlers.handle_structura_cli))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    application.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND, handle_document_message))
    application.add_handler(CallbackQueryHandler(callback_query_handler))
    application.add_handler(InlineQueryHandler(inline_query_handler))

    logger.info("🤖 Bot avviato. In ascolto... 👂")
    application.run_polling()

if __name__ == "__main__":
    main_sync()
