# minecraft_telegram_bot/bot.py
import asyncio # Aggiunto per asyncio.to_thread in scarica_items

from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, InlineQueryHandler, filters
)

# Importa le configurazioni e i logger per primo
from config import TOKEN, CONTAINER, logger # logger da config è già configurato

# Importa i gestori dei comandi
from command_handlers import (
    start, help_command, login, logout, menu_command,
    logs_command, scarica_items_command, cmd_command,
    saveloc_command, edituser,
    give_direct_command, tp_direct_command, weather_direct_command
)

# Importa i gestori dei messaggi e callback
from message_handlers import (
    handle_text_message, callback_query_handler, inline_query_handler
)

# Importa moduli di gestione dati per l'inizializzazione se necessario
import user_management # Per assicurare che users_data sia caricato
import item_management # Per assicurare che ITEMS sia caricato/scaricato

def main():
    # Le verifiche di TOKEN e CONTAINER sono già in config.py e loggano errori/warning
    if not TOKEN:
        # Il logger.critical in config.py ha già segnalato, qui usciamo.
        return

    logger.info("Inizializzazione dell'applicazione Telegram Bot...")
    application = ApplicationBuilder().token(TOKEN).build()

    # Registrazione Comandi
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

    # Registrazione Comandi Diretti
    application.add_handler(CommandHandler("give", give_direct_command))
    application.add_handler(CommandHandler("tp", tp_direct_command))
    application.add_handler(CommandHandler("weather", weather_direct_command))

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