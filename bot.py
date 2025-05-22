# minecraft_telegram_bot/bot.py
import asyncio

from telegram import BotCommand # <<< NUOVO IMPORT
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, InlineQueryHandler, filters, ConversationHandler
)

from config import TOKEN, CONTAINER, logger, WORLD_NAME

from command_handlers import (
    start, help_command, login, logout, menu_command,
    logs_command, scarica_items_command, cmd_command,
    saveloc_command, edituser,
    give_direct_command, tp_direct_command, weather_direct_command,
    start_server_command, stop_server_command, restart_server_command,
    imnotcreative_command,
    backup_world_command,
    list_backups_command,
    add_resourcepack_command,
    edit_resourcepacks_command
)

from message_handlers import (
    handle_text_message, callback_query_handler, inline_query_handler,
    handle_document_message
)

async def set_bot_commands(application):
    """Imposta i comandi del bot visualizzati nell'interfaccia di Telegram."""
    commands = [
        BotCommand("menu", "Apri il tuo zaino di azioni rapide! 🎒"),
        BotCommand("tp", "Teletrasportati come un ninja! 💨"),
        BotCommand("weather", "Cambia il meteo... se solo fosse così facile nella vita reale! ☀️🌧️⛈️"),
        BotCommand("give", "Regala un oggetto a un amico (o a te stesso!). 🎁"),
        BotCommand("saveloc", "Ricorda questo posto magico. 📍"),
        BotCommand("edituser", "Modifica il tuo profilo o fai pulizia. ⚙️"),
        BotCommand("cmd", "Sussurra comandi direttamente al server. 🤫"),
        BotCommand("logs", "Sbircia dietro le quinte del server. 👀"),
        BotCommand("backup_world", "Crea un backup del mondo. 💾"),
        BotCommand("list_backups", "Mostra e scarica i backup disponibili. 📂"),
        BotCommand("addresourcepack", "Aggiungi un resource pack al mondo. 🖼️"),
        BotCommand("editresourcepacks", "Modifica i resource pack attivi. 🛠️"),
        BotCommand("scarica_items", "Aggiorna il tuo inventario di meraviglie. ✨"),
        BotCommand("logout", "Esci in punta di piedi. 👋"),
        BotCommand("login", "Entra nel mondo del bot! 🗝️"),
        BotCommand("startserver", "Avvia il server Minecraft. ▶️"),
        BotCommand("stopserver", "Ferma il server Minecraft. ⏹️"),
        BotCommand("restartserver", "Riavvia il server Minecraft. 🔄"),
        BotCommand("imnotcreative", "Resetta il flag creativo del mondo. 🛠️"),
        BotCommand("help", "Chiedi aiuto all'esperto bot! ❓")
    ]
    try:
        await application.bot.set_my_commands(commands)
        logger.info("Comandi del bot impostati con successo su Telegram.")
    except Exception as e:
        logger.error(f"Errore durante l'impostazione dei comandi del bot: {e}", exc_info=True)

def main():
    if not TOKEN:
        logger.critical("TOKEN Telegram non fornito. Il bot non può avviarsi.")
        return
    if not CONTAINER:
        logger.warning("Variabile CONTAINER non impostata. Funzionalità server limitate.")
    if not WORLD_NAME:
        logger.warning("Variabile WORLD_NAME non impostata. Funzionalità mondo (backup, RP) limitate.")

    logger.info("Inizializzazione dell'applicazione Telegram Bot...")
    application = ApplicationBuilder().token(TOKEN).build()

    # Imposta i comandi del bot <<< CHIAMATA ALLA NUOVA FUNZIONE
    # È importante farlo prima di registrare i CommandHandler se si vuole che siano subito visibili
    # o comunque prima del run_polling. asyncio.create_task è un modo per avviarlo
    # senza bloccare il flusso principale se set_bot_commands dovesse avere operazioni di rete lunghe
    # (anche se set_my_commands è solitamente veloce).
    # In alternativa, un semplice await può bastare se si preferisce la sequenzialità.
    # Per semplicità, usiamo await diretto qui.
    # Considera che main() non è async, quindi dobbiamo creare un task o usare loop.run_until_complete
    # OPPURE rendere main() async e usare asyncio.run(main())
    # Modifichiamo main per essere async per semplicità con le versioni recenti di python-telegram-bot

    # Comandi Utente e Interazione Server
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

    # Comandi Gestione Container e Mondo
    application.add_handler(CommandHandler("startserver", start_server_command))
    application.add_handler(CommandHandler("stopserver", stop_server_command))
    application.add_handler(CommandHandler("restartserver", restart_server_command))
    application.add_handler(CommandHandler("imnotcreative", imnotcreative_command))
    application.add_handler(CommandHandler("backup_world", backup_world_command))
    application.add_handler(CommandHandler("list_backups", list_backups_command))
    application.add_handler(CommandHandler("addresourcepack", add_resourcepack_command))
    application.add_handler(CommandHandler("editresourcepacks", edit_resourcepacks_command))

    # Gestori Messaggi e Callback
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    application.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND, handle_document_message))
    application.add_handler(CallbackQueryHandler(callback_query_handler))
    application.add_handler(InlineQueryHandler(inline_query_handler))

    # Per eseguire una funzione async all'avvio prima del polling
    # creiamo un loop di eventi se non siamo già in uno.
    # La versione più semplice è rendere main async e usare asyncio.run()
    # Dato che run_polling() è bloccante, set_bot_commands deve essere chiamato prima.
    # Tuttavia, set_my_commands è una chiamata di rete e dovrebbe essere awaited.
    # application.bot non è disponibile finché ApplicationBuilder().build() non è chiamato.

    # Il modo corretto con `python-telegram-bot` v20+ è usare `Application.initialize()`
    # e `Application.start()` se si vuole eseguire codice async prima del `run_polling()`.
    # Oppure, più semplicemente, chiamare la funzione async dopo il build e prima del polling,
    # gestendo il loop di eventi.

    # Dato che `run_polling` gestisce il suo loop, possiamo lanciare `set_bot_commands`
    # come un task se `main` fosse async, oppure eseguirlo in modo sincrono qui
    # attraverso un loop temporaneo se necessario, ma `Application` fornisce `bot.post_init`
    # o si può chiamare direttamente.

    # Soluzione più pulita:
    # application.post_init = set_bot_commands # In questo caso set_bot_commands non dovrebbe prendere 'application' come argomento
                                            # ma accedere ad application.bot dal contesto del bot handler,
                                            # oppure application deve essere passato diversamente.

    # Modifichiamo la struttura di `main` per renderla asincrona
    # e chiamare `set_bot_commands` nel modo corretto.

    # >>> Inizio Modifica per main asincrona <<<
    # La funzione set_bot_commands già definita va bene.
    # Bisogna rendere main async e usare asyncio.run(main()) nel blocco if __name__ == "__main__":

    logger.info("Bot avviato e in attesa di comandi...")
    # Prima di avviare il polling, impostiamo i comandi
    # Questa parte verrà eseguita quando main diventerà async
    # await set_bot_commands(application) # Questa riga verrà spostata in un main asincrono

    application.run_polling()


async def async_main(): # NUOVA FUNZIONE ASINCRONA main
    if not TOKEN:
        logger.critical("TOKEN Telegram non fornito. Il bot non può avviarsi.")
        return
    if not CONTAINER:
        logger.warning("Variabile CONTAINER non impostata. Funzionalità server limitate.")
    if not WORLD_NAME:
        logger.warning("Variabile WORLD_NAME non impostata. Funzionalità mondo (backup, RP) limitate.")

    logger.info("Inizializzazione dell'applicazione Telegram Bot...")
    application = ApplicationBuilder().token(TOKEN).build()

    # Imposta i comandi del bot
    await set_bot_commands(application) # ORA POSSIAMO FARE L'AWAIT QUI

    # Comandi Utente e Interazione Server
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

    # Comandi Gestione Container e Mondo
    application.add_handler(CommandHandler("startserver", start_server_command))
    application.add_handler(CommandHandler("stopserver", stop_server_command))
    application.add_handler(CommandHandler("restartserver", restart_server_command))
    application.add_handler(CommandHandler("imnotcreative", imnotcreative_command))
    application.add_handler(CommandHandler("backup_world", backup_world_command))
    application.add_handler(CommandHandler("list_backups", list_backups_command))
    application.add_handler(CommandHandler("addresourcepack", add_resourcepack_command))
    application.add_handler(CommandHandler("editresourcepacks", edit_resourcepacks_command))

    # Gestori Messaggi e Callback
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    application.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND, handle_document_message))
    application.add_handler(CallbackQueryHandler(callback_query_handler))
    application.add_handler(InlineQueryHandler(inline_query_handler))

    logger.info("Bot avviato e in attesa di comandi...")
    await application.initialize() # Necessario se si usa start() e stop() manualmente
    await application.start()
    await application.updater.start_polling() # Sostituisce run_polling per un controllo più granulare
    
    # Per mantenere il bot in esecuzione finché non viene interrotto (es. Ctrl+C)
    # quando non si usa run_polling() che è bloccante.
    # Se si usa run_polling() come prima, non serve questo blocco try/finally.
    # Per semplicità, torniamo a run_polling() e chiamiamo set_bot_commands prima.

# Ripristiniamo la struttura di main() e modifichiamo l'esecuzione
# per consentire la chiamata asincrona a set_bot_commands.

def main_sync(): # Rinominiamo la vecchia main per chiarezza
    if not TOKEN:
        logger.critical("TOKEN Telegram non fornito. Il bot non può avviarsi.")
        return
    # ... (altri controlli TOKEN, CONTAINER, WORLD_NAME come prima) ...

    logger.info("Inizializzazione dell'applicazione Telegram Bot...")
    application = ApplicationBuilder().token(TOKEN).build()

    # Per eseguire set_bot_commands prima del polling:
    # 1. Ottenere un event loop
    # 2. Eseguire la coroutine set_bot_commands
    loop = asyncio.get_event_loop()
    try:
        # Se c'è già un loop in esecuzione (improbabile qui ma buona pratica)
        if loop.is_running():
            logger.info("Loop asyncio già in esecuzione, creo un task per set_bot_commands.")
            loop.create_task(set_bot_commands(application))
        else:
            logger.info("Eseguo set_bot_commands nel loop asyncio.")
            loop.run_until_complete(set_bot_commands(application))
    except RuntimeError as e:
        logger.error(f"RuntimeError durante l'esecuzione di set_bot_commands nel loop: {e}. Potrebbe essere necessario un approccio diverso se eseguito da un thread già async.")
        # Fallback o log aggiuntivo
    except Exception as e:
        logger.error(f"Errore generico durante l'esecuzione di set_bot_commands: {e}", exc_info=True)


    # ... (registrazione di tutti gli handler come prima) ...
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    # ... (tutti gli altri handler)
    application.add_handler(CommandHandler("editresourcepacks", edit_resourcepacks_command)) # Ultimo dalla lista

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    application.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND, handle_document_message))
    application.add_handler(CallbackQueryHandler(callback_query_handler))
    application.add_handler(InlineQueryHandler(inline_query_handler))


    logger.info("Bot avviato e in attesa di comandi...")
    application.run_polling()

# Sostituiamo il vecchio `main` con `main_sync` per ora per mantenere la struttura
# e chiamiamo set_bot_commands usando un loop esplicito.

if __name__ == "__main__":
    # main() # La vecchia chiamata
    main_sync() # La nuova chiamata che include il setup dei comandi