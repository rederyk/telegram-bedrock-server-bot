# minecraft_telegram_bot/message_handlers.py
import asyncio
import subprocess
import uuid
import re
import os
import html
import shutil
import tempfile
from typing import cast
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InlineQueryResultArticle, InputTextMessageContent, Document
)
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import CONTAINER, get_logger, WORLD_NAME
from user_management import (
    is_user_authenticated, get_minecraft_username, set_minecraft_username,
    save_location, get_user_data, get_locations, delete_location,
    users_data, save_users
)
from item_management import get_items
from docker_utils import run_docker_command, get_online_players_from_server
from world_management import get_backups_storage_path

from resource_pack_management import (
    ResourcePackError,
    download_resource_pack_from_url,
    install_resource_pack_from_file,
    manage_world_resource_packs_json,
    get_world_active_packs_with_details
)

from command_handlers import restart_server_command, _offer_server_restart, menu_command, give_direct_command, tp_direct_command, weather_direct_command, saveloc_command

logger = get_logger(__name__)

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return

    uid = update.effective_user.id
    text = update.message.text.strip()

    if not is_user_authenticated(uid):
        await update.message.reply_text("Devi prima effettuare il /login.")
        return

    if context.user_data.get("awaiting_mc_username"):
        if not text:
            await update.message.reply_text("Nome utente Minecraft non valido. Riprova.")
            return
        set_minecraft_username(uid, text)
        await update.message.reply_text(f"👤✅ Username Minecraft '{text}' salvato.")
        next_action = context.user_data.pop("next_action_after_username", None)
        context.user_data.pop("awaiting_mc_username")
        if next_action == "menu": await menu_command(update, context)
        else: await update.message.reply_text("Ora puoi usare i comandi.")
        return

    minecraft_username = get_minecraft_username(uid)
    if not minecraft_username and not context.user_data.get("awaiting_mc_username"):
        context.user_data["awaiting_mc_username"] = True
        context.user_data["next_action_after_username"] = "general_usage"
        await update.message.reply_text("Per favore, inserisci prima il tuo username Minecraft:")
        return

    if context.user_data.get("awaiting_username_edit"):
        set_minecraft_username(uid, text)
        context.user_data.pop("awaiting_username_edit")
        await update.message.reply_text(f"👤✅ Username aggiornato a: {text}")
        return

    if context.user_data.get("awaiting_saveloc_name"):
        context.user_data.pop("awaiting_saveloc_name")
        await update.message.reply_text(f"💾⏳ Tentativo di salvare posizione '{html.escape(text)}'...")
        return

    if context.user_data.get("awaiting_give_prefix"):
        context.user_data.pop("awaiting_give_prefix")
        await update.message.reply_text(f"📦🔍 Ricerca item con prefisso '{html.escape(text)}'...")
        return

    if context.user_data.get("awaiting_item_quantity"):
        context.user_data.pop("selected_item_for_give", None)
        context.user_data.pop("awaiting_item_quantity", None)
        await update.message.reply_text(f"📦⏳ Tentativo di dare item con quantità '{html.escape(text)}'...")
        return

    if context.user_data.get("awaiting_tp_coords_input"):
        context.user_data.pop("awaiting_tp_coords_input", None)
        await update.message.reply_text(f"🚀⏳ Tentativo di teleport a '{html.escape(text)}'...")
        return

    if context.user_data.get("awaiting_resource_pack"):
        context.user_data.pop("awaiting_resource_pack", None)
        if not WORLD_NAME:
            await update.message.reply_text("⚠️ `WORLD_NAME` non configurato.")
            return
        if text.startswith("http://") or text.startswith("https://"):
            await update.message.reply_text(f"🔗📦 Ricevuto URL. Download e installazione...")
            temp_dir = tempfile.mkdtemp()
            try:
                downloaded_file_path = await download_resource_pack_from_url(text, temp_dir)
                _, pack_uuid, pack_version, pack_name = await asyncio.to_thread(
                    install_resource_pack_from_file, downloaded_file_path, os.path.basename(downloaded_file_path)
                )
                await asyncio.to_thread(
                    manage_world_resource_packs_json, WORLD_NAME, pack_uuid_to_add=pack_uuid, pack_version_to_add=pack_version, add_at_beginning=True
                )
                await update.message.reply_text(
                    f"📦✅ RP '{html.escape(pack_name)}' installato e attivato (priorità più alta)!"
                )
                await _offer_server_restart(update, context, f"dopo aggiunta di '{html.escape(pack_name)}'")
            except Exception as e:
                logger.error(f"🔗❌ Errore aggiunta RP da URL: {e}", exc_info=True)
                await update.message.reply_text(f"⚠️ Errore: {html.escape(str(e))}")
            finally:
                if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
        else:
            await update.message.reply_text("URL non valido. Usa /addresourcepack per riprovare.")
        return

    if context.user_data.get("awaiting_rp_move_position"):
        rp_to_move_uuid = context.user_data.get("rp_to_move_uuid")
        rp_to_move_name = context.user_data.get("rp_to_move_name", "Pacchetto Selezionato")

        context.user_data.pop("awaiting_rp_move_position", None)
        context.user_data.pop("rp_to_move_uuid", None)
        context.user_data.pop("rp_to_move_name", None)

        if not rp_to_move_uuid:
            await update.message.reply_text("Errore: UUID del pacchetto da spostare non trovato. Riprova.")
            return
        try:
            new_pos_1_based = int(text)
            if new_pos_1_based <= 0:
                await update.message.reply_text("Posizione non valida. Inserisci un numero positivo.")
                return

            new_pos_0_based = new_pos_1_based - 1

            await asyncio.to_thread(
                manage_world_resource_packs_json,
                WORLD_NAME,
                pack_uuid_to_move=rp_to_move_uuid,
                new_index_for_move=new_pos_0_based
            )
            await update.message.reply_text(
                f"📦↕️ RP '{html.escape(rp_to_move_name)}' spostato alla posizione {new_pos_1_based}."
            )
            await _offer_server_restart(update, context, f"dopo aver spostato '{html.escape(rp_to_move_name)}'")
        except ValueError:
            await update.message.reply_text("Posizione non valida. Inserisci un numero.")
        except ResourcePackError as rpe:
            await update.message.reply_text(f"⚠️ Errore spostando il pacchetto: {html.escape(str(rpe))}")
        except Exception as e:
            logger.error(f"🆘 Errore imprevisto spostamento RP: {e}", exc_info=True)
            await update.message.reply_text(f"🆘 Errore imprevisto: {html.escape(str(e))}")
        return

    if not text.startswith('/'):
        await update.message.reply_text("Comando non riconosciuto. Usa /help.")

async def handle_document_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.document: return

    uid = update.effective_user.id
    if not is_user_authenticated(uid):
        logger.warning(f"👤⚠️ Documento da utente non autenticato {uid}")
        return

    if context.user_data.get("awaiting_resource_pack"):
        context.user_data.pop("awaiting_resource_pack", None)
        doc = update.message.document
        if not doc.file_name or not (doc.file_name.lower().endswith((".zip", ".mcpack"))):
            await update.message.reply_text("⚠️ Formato file non supportato. Invia .zip o .mcpack.")
            return
        if not WORLD_NAME:
            await update.message.reply_text("⚠️ `WORLD_NAME` non configurato.")
            return

        await update.message.reply_text(f"📄📦 Ricevuto file '{html.escape(doc.file_name)}'. Installazione...")
        temp_dir = tempfile.mkdtemp()
        downloaded_path = os.path.join(temp_dir, "telegram_dl_" + doc.file_name)
        try:
            file_on_telegram = await context.bot.get_file(doc.file_id)
            await file_on_telegram.download_to_drive(custom_path=downloaded_path)

            _, pack_uuid, pack_version, pack_name = await asyncio.to_thread(
                install_resource_pack_from_file, downloaded_path, doc.file_name
            )
            await asyncio.to_thread(
                manage_world_resource_packs_json, WORLD_NAME, pack_uuid_to_add=pack_uuid, pack_version_to_add=pack_version, add_at_beginning=True
            )
            await update.message.reply_text(
                f"📦✅ RP '{html.escape(pack_name)}' installato e attivato (priorità più alta)!"
            )
            await _offer_server_restart(update, context, f"dopo aggiunta di '{html.escape(pack_name)}'")
        except Exception as e:
            logger.error(f"📄❌ Errore aggiunta RP da file: {e}", exc_info=True)
            await update.message.reply_text(f"⚠️ Errore: {html.escape(str(e))}")
        finally:
            if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
        return

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

    if not is_user_authenticated(uid):
        await query.edit_message_text("Errore: non autenticato.")
        return

    if data.startswith("rp_manage:"):
        pack_uuid_to_manage = data.split(":", 1)[1]
        active_packs = await asyncio.to_thread(get_world_active_packs_with_details, WORLD_NAME)
        pack_details = next((p for p in active_packs if p['uuid'] == pack_uuid_to_manage), None)
        pack_name_display = pack_details['name'][:30] if pack_details else pack_uuid_to_manage[:8]

        context.user_data["selected_rp_uuid_for_manage"] = pack_uuid_to_manage
        context.user_data["selected_rp_name_for_manage"] = pack_name_display

        keyboard = [
            [InlineKeyboardButton(f"🗑️ Elimina '{html.escape(pack_name_display)}'", callback_data=f"rp_action:delete_confirm:{pack_uuid_to_manage}")],
            [InlineKeyboardButton(f"↕️ Sposta '{html.escape(pack_name_display)}'", callback_data=f"rp_action:move_prompt:{pack_uuid_to_manage}")],
            [InlineKeyboardButton("↩️ Annulla", callback_data="rp_action:cancel_manage")]
        ]
        await query.edit_message_text(f"📦 Gestisci: {html.escape(pack_name_display)}\nCosa vuoi fare?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
        return

    elif data.startswith("rp_action:"):
        action_parts = data.split(":")
        action = action_parts[1]

        rp_uuid = context.user_data.get("selected_rp_uuid_for_manage")
        rp_name = context.user_data.get("selected_rp_name_for_manage", "Pacchetto Selezionato")
        if len(action_parts) > 2:
            rp_uuid_from_cb = action_parts[2]
            if not rp_uuid: rp_uuid = rp_uuid_from_cb

        if action == "delete_confirm":
            if not rp_uuid:
                await query.edit_message_text("Errore: UUID non trovato per eliminazione.")
                return
            keyboard = [
                [InlineKeyboardButton(f"✅ Sì, elimina '{html.escape(rp_name)}'", callback_data=f"rp_action:delete_execute:{rp_uuid}")],
                [InlineKeyboardButton("❌ No, annulla", callback_data="rp_action:cancel_manage")]
            ]
            await query.edit_message_text(f"Sei sicuro di voler eliminare il RP '{html.escape(rp_name)}' dalla lista attivi?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

        elif action == "delete_execute":
            if not rp_uuid:
                await query.edit_message_text("Errore: UUID non trovato per eliminazione.")
                return
            try:
                await asyncio.to_thread(manage_world_resource_packs_json, WORLD_NAME, pack_uuid_to_remove=rp_uuid)
                await query.edit_message_text(f"🗑️✅ RP '{html.escape(rp_name)}' rimosso dalla lista attivi.")
                await _offer_server_restart(update, context, f"dopo aver rimosso '{html.escape(rp_name)}'")
            except Exception as e:
                await query.edit_message_text(f"⚠️ Errore rimozione: {html.escape(str(e))}")
            context.user_data.pop("selected_rp_uuid_for_manage", None)
            context.user_data.pop("selected_rp_name_for_manage", None)

        elif action == "move_prompt":
            if not rp_uuid:
                await query.edit_message_text("Errore: UUID non trovato per spostamento.")
                return
            context.user_data["awaiting_rp_move_position"] = True
            context.user_data["rp_to_move_uuid"] = rp_uuid
            context.user_data["rp_to_move_name"] = rp_name
            await query.edit_message_text(f"Inserisci la nuova posizione (numero) per '{html.escape(rp_name)}'.\n(Es. 1 per priorità più bassa).")

        elif action == "restart_server":
            await query.edit_message_text("🔄 Richiesta di riavvio server ricevuta...")
            await restart_server_command(update, cast(ContextTypes.DEFAULT_TYPE, context))

        elif action == "restart_later":
            await query.edit_message_text("Ok, puoi riavviare il server manualmente con /restartserver.")

        elif action == "cancel_manage" or action == "cancel_edit":
            await query.edit_message_text("Operazione annullata.")
            context.user_data.pop("selected_rp_uuid_for_manage", None)
            # ... (clear other related user_data keys) ...
        return

    if data == "edit_username":
        context.user_data["awaiting_username_edit"] = True
        await query.edit_message_text("Ok, inserisci il nuovo username Minecraft:")
        return

async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.inline_query.answer([], cache_time=10)