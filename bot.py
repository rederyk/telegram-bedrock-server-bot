# minecraft_telegram_bot/bot.py
import asyncio 

from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, InlineQueryHandler, filters
)

from config import TOKEN, CONTAINER, logger # WORLD_NAME non serve qui direttamente

from command_handlers import (
    start, help_command, login, logout, menu_command,
    logs_command, scarica_items_command, cmd_command,
    saveloc_command, edituser,
    give_direct_command, tp_direct_command, weather_direct_command,
    start_server_command, stop_server_command, restart_server_command,
    imnotcreative_command # <--- IMPORT NUOVO COMANDO
)

from message_handlers import (
    handle_text_message, callback_query_handler, inline_query_handler
)

# user_management and item_management non serve importarli qui direttamente
# se sono usati solo dai command_handlers

def main():
    if not TOKEN:
        logger.error("TOKEN non fornito. Uscita.") # Aggiunto logger per errore
        return

    logger.info("Inizializzazione dell'applicazione Telegram Bot...")
    application = ApplicationBuilder().token(TOKEN).build()

    # Registrazione Comandi Utente e Interazione Server
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("login", login))
    application.add_handler(CommandHandler("logout", logout))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("logs", logs_command))
    application.add_handler(CommandHandler("scarica_items", scarica_items_command))
    application.add_handler(CommandHandler("cmd", cmd_command))
    application.add_handler(CommandHandler("saveloc", saveloc_command))
    application.add_handler(CommandHandler("edituser", edituser))
    application.add_handler(CommandHandler("give", give_direct_command))
    application.add_handler(CommandHandler("tp", tp_direct_command))
    application.add_handler(CommandHandler("weather", weather_direct_command))

    # Registrazione Comandi Gestione Container Server
    application.add_handler(CommandHandler("startserver", start_server_command))
    application.add_handler(CommandHandler("stopserver", stop_server_command))
    application.add_handler(CommandHandler("restartserver", restart_server_command))
    application.add_handler(CommandHandler("imnotcreative", imnotcreative_command)) # <-- REGISTRA NUOVO COMANDO


    # Registrazione Gestori di Messaggi e Callback
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_text_message
    ))
    application.add_handler(CallbackQueryHandler(callback_query_handler))
    application.add_handler(InlineQueryHandler(inline_query_handler))

    logger.info("Bot avviato e in attesa di comandi...")
    application.run_polling()

if __name__ == "__main__":
    main()