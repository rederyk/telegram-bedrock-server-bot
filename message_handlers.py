# minecraft_telegram_bot/message_handlers.py
import asyncio
import subprocess
import uuid
import re
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InlineQueryResultArticle, InputTextMessageContent
)
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import CONTAINER, get_logger
from user_management import (
    is_user_authenticated, get_minecraft_username, set_minecraft_username,
    save_location, get_user_data, get_locations, delete_location,
    users_data # Accesso diretto per modifica username, da valutare se creare setter specifico
)
from item_management import get_items
from docker_utils import run_docker_command, get_online_players_from_server
# Importa i comandi per rieseguirli dopo l'inserimento dell'username
from command_handlers import menu_command, give_direct_command, tp_direct_command, weather_direct_command, saveloc_command


logger = get_logger(__name__)

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()

    if not is_user_authenticated(uid):
        await update.message.reply_text("Devi prima effettuare il /login.")
        return

    # Gestione inserimento username Minecraft
    if context.user_data.get("awaiting_mc_username"):
        if not text:
            await update.message.reply_text("Nome utente Minecraft non valido. Riprova.")
            return
        set_minecraft_username(uid, text)
        context.user_data.pop("awaiting_mc_username")
        await update.message.reply_text(f"Username Minecraft '{text}' salvato.")

        next_action = context.user_data.pop("next_action", None)
        if next_action == "menu":
            await menu_command(update, context)
        elif next_action == "give":
            await give_direct_command(update, context)
        elif next_action == "tp":
            await tp_direct_command(update, context)
        elif next_action == "weather":
            await weather_direct_command(update, context)
        elif next_action == "saveloc":
             await saveloc_command(update,context) # Richiama saveloc per chiedere il nome
        else:
            await update.message.reply_text("Ora puoi usare i comandi che richiedono l'username (es. /menu).")
        return

    minecraft_username = get_minecraft_username(uid)
    if not minecraft_username: # Sicurezza aggiuntiva
        context.user_data["awaiting_mc_username"] = True
        await update.message.reply_text("Per favore, inserisci prima il tuo username Minecraft:")
        return

    # Gestione modifica username
    if context.user_data.get("awaiting_username_edit"):
        if not text:
            await update.message.reply_text("Nome utente non valido. Riprova.")
            return
        # Accesso diretto a users_data per la modifica, non ideale ma semplice
        users_data[uid]["minecraft_username"] = text
        from user_management import save_users # Importazione locale per evitare circular import a livello di modulo
        save_users()
        context.user_data.pop("awaiting_username_edit")
        await update.message.reply_text(f"Username aggiornato a: {text}")
        return

    # Gestione salvataggio nome posizione
    if context.user_data.get("awaiting_saveloc_name"):
        location_name = text
        if not location_name:
            await update.message.reply_text("Nome posizione non valido. Riprova.")
            return
        context.user_data.pop("awaiting_saveloc_name")

        if not CONTAINER:
            await update.message.reply_text("Impossibile salvare la posizione: CONTAINER non configurato.")
            return

        # Ottieni coordinate
        docker_cmd_get_pos = [
            "docker", "exec", CONTAINER, "send-command",
            f"execute as {minecraft_username} at @s run tp @s ~ ~ ~0.0001" # Piccolo offset per triggerare l'output
        ]
        try:
            logger.info(f"Esecuzione per ottenere coordinate: {' '.join(docker_cmd_get_pos)}")
            await run_docker_command(docker_cmd_get_pos, read_output=False, timeout=10)
            await asyncio.sleep(1.0) # Dai tempo al server di loggare

            log_args = ["docker", "logs", "--tail", "100", CONTAINER]
            output = await run_docker_command(log_args, read_output=True, timeout=5)

            pattern = rf"Teleported {re.escape(minecraft_username)} to ([0-9\.\-]+),\s*([0-9\.\-]+),\s*([0-9\.\-]+)"
            # Per Bedrock, il formato potrebbe essere diverso, es:
            # "[INFO] Teleported <PlayerName> to <x>, <y>, <z>"
            # Dovremmo cercare il pattern più recente nei log.
            matches = re.findall(pattern, output)
            if not matches:
                 # Prova un pattern alternativo per Bedrock (più generico, potrebbe richiedere affinamenti)
                pattern_bedrock = rf"Teleported {re.escape(minecraft_username)} to ([0-9\.\-]+), ([0-9\.\-]+), ([0-9\.\-]+)"
                matches = re.findall(pattern_bedrock, output)

            if not matches:
                logger.warning(f"Nessuna coordinata trovata nei log per {minecraft_username} dopo /saveloc.")
                logger.debug(f"Output log per saveloc: {output}")
                await update.message.reply_text(
                    "Impossibile trovare le coordinate nei log. Assicurati di essere in gioco, che i comandi siano abilitati e che l'output del comando 'tp' sia visibile nei log. Riprova più tardi."
                )
                return

            x_str, y_str, z_str = matches[-1] # Prendi l'ultima occorrenza
            coords = {"x": float(x_str), "y": float(y_str), "z": float(z_str)}

            save_location(uid, location_name, coords)
            await update.message.reply_text(
                f"✅ Posizione '{location_name}' salvata: X={coords['x']:.2f}, Y={coords['y']:.2f}, Z={coords['z']:.2f}"
            )
        except asyncio.TimeoutError:
            await update.message.reply_text("Timeout durante il salvataggio della posizione. Riprova.")
        except subprocess.CalledProcessError as e:
            await update.message.reply_text(
                f"Errore del server Minecraft durante il salvataggio: {e.stderr or e.output or e}. "
                "Potrebbe essere necessario abilitare i comandi o verificare l'username."
            )
        except ValueError as e: # Per CONTAINER non configurato
             await update.message.reply_text(str(e))
        except Exception as e:
            logger.error(f"Errore in /saveloc (esecuzione comando): {e}", exc_info=True)
            await update.message.reply_text("Si è verificato un errore salvando la posizione.")
        return

    # Gestione prefisso item per /give
    if context.user_data.get("awaiting_give_prefix"):
        prefix = text.lower()
        all_items = get_items()
        matches = [
            i for i in all_items
            if prefix in i["id"].lower() or prefix in i["name"].lower() # Modificato per cercare sottostringhe
        ]
        if not matches:
            await update.message.reply_text("Nessun item trovato con quel nome/ID. Riprova o usa /menu.")
        else:
            buttons = [
                InlineKeyboardButton(
                    f'{i["name"]} ({i["id"]})', callback_data=f'give_item_select:{i["id"]}'
                ) for i in matches[:20] # Limita a 20 risultati per non appesantire
            ]
            keyboard = [buttons[j:j+1] for j in range(len(buttons))] # Un bottone per riga
            await update.message.reply_text(
                f"Ho trovato {len(matches)} item (mostro i primi {len(buttons)}). Scegli un item:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        context.user_data.pop("awaiting_give_prefix")
        return

    # Gestione quantità item
    if context.user_data.get("awaiting_item_quantity"):
        if not CONTAINER:
            await update.message.reply_text("Errore: CONTAINER non configurato per il comando give.")
            context.user_data.pop("awaiting_item_quantity", None)
            context.user_data.pop("selected_item_for_give", None)
            return

        try:
            quantity = int(text)
            if quantity <= 0:
                raise ValueError("La quantità deve essere positiva.")

            item_id = context.user_data.get("selected_item_for_give")
            if not item_id:
                await update.message.reply_text(
                    "Errore interno: item non selezionato. Riprova da /menu o /give."
                )
                context.user_data.pop("awaiting_item_quantity", None)
                return

            cmd_text = f"give {minecraft_username} {item_id} {quantity}"
            docker_cmd_args = ["docker", "exec", CONTAINER, "send-command", cmd_text]
            await run_docker_command(docker_cmd_args, read_output=False)
            await update.message.reply_text(f"Comando eseguito: /give {minecraft_username} {item_id} {quantity}")

        except ValueError as e:
            if "La quantità deve essere positiva" in str(e):
                 await update.message.reply_text("Inserisci un numero valido (intero, maggiore di zero) per la quantità.")
            else: # Per CONTAINER non configurato o altri ValueError
                 await update.message.reply_text(str(e))
        except asyncio.TimeoutError:
            await update.message.reply_text("Timeout eseguendo il comando give.")
        except subprocess.CalledProcessError as e:
            await update.message.reply_text(f"Errore dal server Minecraft: {e.stderr or e.output or e}")
        except Exception as e:
            logger.error(f"Errore imprevisto in handle_message (give quantity): {e}", exc_info=True)
            await update.message.reply_text(f"Errore imprevisto: {e}")
        finally:
            context.user_data.pop("selected_item_for_give", None)
            context.user_data.pop("awaiting_item_quantity", None)
        return

    # Gestione coordinate TP
    if context.user_data.get("awaiting_tp_coords_input"):
        if not CONTAINER:
            await update.message.reply_text("Errore: CONTAINER non configurato per il comando teleport.")
            context.user_data.pop("awaiting_tp_coords_input", None)
            return

        parts = text.split()
        if len(parts) != 3:
            await update.message.reply_text(
                "Formato coordinate non valido. Usa: x y z (es. 100 64 -200). Riprova o /menu, /tp."
            )
        else:
            try:
                x, y, z = map(float, parts) # o int se preferisci coordinate intere
                cmd_text = f"tp {minecraft_username} {x} {y} {z}"
                docker_cmd_args = ["docker", "exec", CONTAINER, "send-command", cmd_text]
                await run_docker_command(docker_cmd_args, read_output=False)
                await update.message.reply_text(f"Comando eseguito: /tp {minecraft_username} {x} {y} {z}")
            except ValueError as e:
                if "could not convert string to float" in str(e).lower() or "invalid literal for int" in str(e).lower():
                    await update.message.reply_text(
                        "Le coordinate devono essere numeri validi (es. 100 64.5 -200). Riprova o /menu, /tp."
                    )
                else: # Per CONTAINER non configurato o altri ValueError
                    await update.message.reply_text(str(e))
            except asyncio.TimeoutError:
                await update.message.reply_text("Timeout eseguendo il comando teleport.")
            except subprocess.CalledProcessError as e:
                await update.message.reply_text(f"Errore dal server Minecraft: {e.stderr or e.output or e}")
            except Exception as e:
                logger.error(f"Errore imprevisto in handle_message (tp coords): {e}", exc_info=True)
                await update.message.reply_text(f"Errore imprevisto: {e}")
            finally:
                context.user_data.pop("awaiting_tp_coords_input", None)
        return

    # Se nessun stato ha gestito il messaggio e non è un comando
    if not text.startswith('/'):
        await update.message.reply_text(
            "Comando testuale non riconosciuto o stato non attivo. "
            "Usa /menu per vedere le opzioni o /help per la lista comandi."
        )


async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip().lower()
    results = []
    # Non richiedere autenticazione per query inline, ma l'utente dovrà essere autenticato per usare il comando risultante.

    if query: # Solo se c'è una query
        all_items = get_items()
        if not all_items: # Se ITEMS è vuoto o None
            logger.warning("Inline query: lista ITEMS vuota o non disponibile.")
        else:
            matches = [
                i for i in all_items
                if query in i["id"].lower() or query in i["name"].lower()
            ]
            results = [
                InlineQueryResultArticle(
                    id=str(uuid.uuid4()), # ID univoco per ogni risultato
                    title=i["name"],
                    description=f'ID: {i["id"]}',
                    input_message_content=InputTextMessageContent(
                        f'/give {{MINECRAFT_USERNAME}} {i["id"]} 1' # Placeholder per l'username
                    )
                ) for i in matches[:20] # Limita i risultati
            ]
    # cache_time basso per sviluppo, aumentalo in produzione (es. 300-3600s)
    await update.inline_query.answer(results, cache_time=10)


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Importante per far sparire l'icona di caricamento sul client

    uid = query.from_user.id
    data = query.data

    if not is_user_authenticated(uid):
        await query.edit_message_text("Errore: non sei autenticato. Usa /login.")
        return

    minecraft_username = get_minecraft_username(uid)
    if not minecraft_username and not data.startswith("edit_username"): # L'edit username non richiede un MC username esistente
        context.user_data["awaiting_mc_username"] = True
        # Potresti voler salvare 'data' in user_data per rieseguire l'azione dopo l'inserimento dell'username
        await query.edit_message_text(
            "Il tuo username Minecraft non è impostato. Per favore, invialo in chat."
        )
        return

    # Controllo CONTAINER per azioni che lo richiedono
    actions_requiring_container = [
        "give_item_select:", "tp_player:", "tp_coords_input", "weather_set:",
        "tp_saved:", "menu_give", "menu_tp", "menu_weather" # Anche i menu che portano ad azioni Docker
    ]
    if not CONTAINER and any(data.startswith(action_prefix) for action_prefix in actions_requiring_container):
         # Eccezione per 'delete_location' e 'edit_username' che non usano CONTAINER
        if not (data == "delete_location" or data.startswith("delete_loc:") or data == "edit_username"):
            await query.edit_message_text(
                "Errore: La variabile CONTAINER non è impostata nel bot. "
                "Impossibile eseguire questa azione."
            )
            return

    try:
        if data == "edit_username":
            context.user_data["awaiting_username_edit"] = True
            await query.edit_message_text("Ok, inserisci il nuovo username Minecraft:")

        elif data == "delete_location":
            user_locs = get_locations(uid)
            if not user_locs:
                await query.edit_message_text("Non hai posizioni salvate.")
                return
            buttons = [
                [InlineKeyboardButton(f"❌ {name}", callback_data=f"delete_loc:{name}")]
                for name in user_locs
            ]
            await query.edit_message_text(
                "Seleziona la posizione da cancellare:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )

        elif data.startswith("delete_loc:"):
            name_to_delete = data.split(":", 1)[1]
            if delete_location(uid, name_to_delete):
                await query.edit_message_text(f"Posizione «{name_to_delete}» cancellata 🔥")
            else:
                await query.edit_message_text(f"Posizione «{name_to_delete}» non trovata.")

        elif data == "menu_give": # Bottone dal /menu
            context.user_data["awaiting_give_prefix"] = True
            await query.edit_message_text(
                "Ok, inviami il nome (o parte del nome/ID) dell'oggetto che vuoi dare:"
            )

        elif data.startswith("give_item_select:"): # Selezione da lista oggetti
            item_id = data.split(":", 1)[1]
            context.user_data["selected_item_for_give"] = item_id
            context.user_data["awaiting_item_quantity"] = True
            await query.edit_message_text(f"Item selezionato: {item_id}.\nInserisci la quantità desiderata:")

        elif data == "menu_tp": # Bottone dal /menu
            online_players = await get_online_players_from_server()
            buttons = []
            if online_players: # Aggiungi giocatori online solo se ce ne sono
                buttons.extend([
                    InlineKeyboardButton(p, callback_data=f"tp_player:{p}")
                    for p in online_players
                ])
            buttons.append(InlineKeyboardButton("📍 Inserisci coordinate", callback_data="tp_coords_input"))
            user_locs = get_locations(uid)
            for name in user_locs:
                buttons.append(InlineKeyboardButton(f"📌 {name}", callback_data=f"tp_saved:{name}"))

            if not buttons: # Nessun giocatore, nessuna loc salvata, solo coordinate
                 await query.edit_message_text(
                    "Nessun giocatore online e nessuna posizione salvata. "
                    "Puoi solo inserire le coordinate manualmente.",
                    reply_markup=InlineKeyboardMarkup([[buttons[0]]]) # Solo "Inserisci coordinate"
                 )
                 return

            keyboard_layout = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
            markup = InlineKeyboardMarkup(keyboard_layout)
            text_reply = "Scegli una destinazione:"
            if not online_players and not CONTAINER:
                 text_reply = ("Impossibile ottenere lista giocatori (CONTAINER non settato).\n"
                               "Scegli tra posizioni salvate o coordinate.")
            elif not online_players:
                 text_reply = "Nessun giocatore online.\nScegli tra posizioni salvate o coordinate:"
            await query.edit_message_text(text_reply, reply_markup=markup)


        elif data.startswith("tp_saved:"):
            location_name = data.split(":", 1)[1]
            user_locs = get_locations(uid)
            loc_coords = user_locs.get(location_name)
            if not loc_coords:
                await query.edit_message_text(f"Posizione '{location_name}' non trovata.")
                return
            x, y, z = loc_coords["x"], loc_coords["y"], loc_coords["z"]
            cmd_text = f"tp {minecraft_username} {x} {y} {z}"
            docker_args = ["docker", "exec", CONTAINER, "send-command", cmd_text]
            await run_docker_command(docker_args, read_output=False)
            await query.edit_message_text(f"Teleport eseguito su '{location_name}': {x:.2f}, {y:.2f}, {z:.2f}")

        elif data == "tp_coords_input": # Richiesta di inserimento coordinate
            context.user_data["awaiting_tp_coords_input"] = True
            await query.edit_message_text("Inserisci le coordinate nel formato: `x y z` (es. `100 64 -200`)")

        elif data.startswith("tp_player:"):
            target_player = data.split(":", 1)[1]
            cmd_text = f"tp {minecraft_username} {target_player}"
            docker_cmd_args = ["docker", "exec", CONTAINER, "send-command", cmd_text]
            await run_docker_command(docker_cmd_args, read_output=False)
            await query.edit_message_text(f"Teleport verso {target_player} eseguito!")

        elif data == "menu_weather": # Bottone dal /menu
            buttons = [
                [InlineKeyboardButton("☀️ Sereno (Clear)", callback_data="weather_set:clear")],
                [InlineKeyboardButton("🌧 Pioggia (Rain)", callback_data="weather_set:rain")],
                [InlineKeyboardButton("⛈ Temporale (Thunder)", callback_data="weather_set:thunder")]
            ]
            await query.edit_message_text(
                "Scegli le condizioni meteo:", reply_markup=InlineKeyboardMarkup(buttons)
            )

        elif data.startswith("weather_set:"):
            weather_condition = data.split(":", 1)[1]
            cmd_text = f"weather {weather_condition}"
            docker_cmd_args = ["docker", "exec", CONTAINER, "send-command", cmd_text]
            await run_docker_command(docker_cmd_args, read_output=False)
            await query.edit_message_text(f"Meteo impostato su: {weather_condition.capitalize()}")

        else:
            await query.edit_message_text("Azione non riconosciuta o scaduta.")

    except asyncio.TimeoutError:
        await query.edit_message_text("Timeout eseguendo l'azione richiesta. Riprova.")
    except subprocess.CalledProcessError as e:
        error_detail = e.stderr or e.output or str(e)
        await query.edit_message_text(f"Errore dal server Minecraft: {error_detail}. Riprova o contatta un admin.")
        logger.error(f"CalledProcessError in button_handler for data '{data}': {error_detail}")
    except ValueError as e: # Per CONTAINER non configurato o altri ValueError
        await query.edit_message_text(str(e))
    except Exception as e:
        logger.error(f"Errore imprevisto in button_handler for data '{data}': {e}", exc_info=True)
        await query.edit_message_text("Si è verificato un errore imprevisto. Riprova più tardi.")