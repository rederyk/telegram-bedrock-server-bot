# minecraft_telegram_bot/world_management.py
import os
import io
import sys
import tempfile # Per creare file temporanei in modo sicuro
import nbtlib
import shutil # Importato per shutil.make_archive, anche se non usato direttamente qui, ma utile per la logica di backup
from datetime import datetime # Importato per timestamp, utile per i nomi dei backup
import asyncio # Aggiunto per asyncio.to_thread se necessario per operazioni NBT lunghe

from config import get_logger, BACKUPS_DIR_NAME
logger = get_logger(__name__)

try:
    from nbtlib.nbt import MalformedFileError, NBTError
    logger.info("✅ Importazioni NBT (MalformedFileError, NBTError) riuscite.")
except ImportError:
    logger.warning(
        "⚠️  Importazioni NBT (MalformedFileError, NBTError) fallite. "
        "Questo è atteso con nbtlib < 3.0. "
        "Gestione errori NBT specifica compromessa; fallback a 'Exception'."
    )
    MalformedFileError = Exception # type: ignore
    NBTError = Exception # type: ignore

from nbtlib.tag import Byte # type: ignore

BEDROCK_DATA_PATH = "/bedrockData"

def get_world_level_dat_path(world_name: str) -> str | None:
    if not world_name:
        logger.error("❌ Nome mondo mancante per trovare level.dat.")
        return None

    potential_path_worlds_subdir = os.path.join(BEDROCK_DATA_PATH, "worlds", world_name, "level.dat")
    if os.path.exists(potential_path_worlds_subdir):
        logger.info(f"🔍 Trovato level.dat: {potential_path_worlds_subdir}")
        return potential_path_worlds_subdir

    potential_path_direct_subdir = os.path.join(BEDROCK_DATA_PATH, world_name, "level.dat")
    if os.path.exists(potential_path_direct_subdir):
        logger.info(f"🔍 Trovato level.dat: {potential_path_direct_subdir}")
        return potential_path_direct_subdir

    logger.warning(f"❓ level.dat non trovato per '{world_name}'. Controllati: "
                   f"'{potential_path_worlds_subdir}' e '{potential_path_direct_subdir}'.")
    return None


def get_world_directory_path(world_name: str) -> str | None:
    level_dat_path = get_world_level_dat_path(world_name)
    if level_dat_path and os.path.exists(level_dat_path):
        world_dir = os.path.dirname(level_dat_path)
        logger.info(f"🌍 Directory mondo '{world_name}': {world_dir}")
        return world_dir
    logger.warning(f"❓ Directory mondo '{world_name}' non determinata da level.dat.")
    return None

def get_backups_storage_path() -> str:
    path = os.path.join(BEDROCK_DATA_PATH, BACKUPS_DIR_NAME)
    try:
        os.makedirs(path, exist_ok=True)
        logger.info(f"💾 Directory backup creata/verificata: {path}")
    except OSError as e:
        logger.error(f"❌ Errore creazione directory backup {path}: {e}")
    return path

def get_resource_packs_main_folder_path() -> str | None:
    path = os.path.join(BEDROCK_DATA_PATH, "resource_packs")
    try:
        logger.info(f"📦 Percorso cartella resource pack: {path}")
        return path
    except OSError as e:
        logger.error(f"❌ Errore directory resource pack {path}: {e}")
        return None

def get_world_specific_resource_packs_json_path(world_name: str) -> str | None:
    world_dir = get_world_directory_path(world_name)
    if world_dir:
        json_path = os.path.join(world_dir, "world_resource_packs.json")
        logger.info(f"📄 Percorso world_resource_packs.json per '{world_name}': {json_path}")
        return json_path
    logger.warning(f"❓ Dir mondo per '{world_name}' (world_resource_packs.json) non trovata.")
    return None

async def reset_creative_flag(world_name: str) -> tuple[bool, str]:
    level_dat_path = get_world_level_dat_path(world_name)
    if not level_dat_path:
        return False, f"Impossibile localizzare level.dat per il mondo '{world_name}'."

    if not os.path.exists(level_dat_path):
        logger.error(f"📄❌ File level.dat non trovato al percorso finale: {level_dat_path}")
        return False, f"File level.dat non trovato: {level_dat_path}"

    original_header = None
    modified_nbt_data_bytes = None

    try:
        def _process_nbt_file():
            nonlocal original_header, modified_nbt_data_bytes
            with open(level_dat_path, "rb") as f:
                original_header = f.read(8)
                if len(original_header) < 8:
                    logger.error(f"❌ level.dat ({level_dat_path}) corrotto o header mancante.")
                    raise ValueError("level.dat troppo corto o corrotto (header mancante).")
                f.seek(0)
                nbt_file = nbtlib.File.parse(f, byteorder='little') # type: ignore
                logger.info(f"📄✅ File NBT parsato. Tipo: {type(nbt_file)}")

            tag_to_find_pascal_case = "HasBeenLoadedInCreative"
            tag_to_find_camel_case = "hasBeenLoadedInCreative"
            tag_found_name = None

            if tag_to_find_camel_case in nbt_file: # type: ignore
                tag_found_name = tag_to_find_camel_case
            elif tag_to_find_pascal_case in nbt_file: # type: ignore
                tag_found_name = tag_to_find_pascal_case

            if tag_found_name:
                logger.info(f"🏷️  Trovato tag NBT '{tag_found_name}' in {level_dat_path}.")
                current_value = nbt_file[tag_found_name] # type: ignore

                if isinstance(current_value, Byte) and current_value == 0:
                    logger.info(f"ℹ️  Tag '{tag_found_name}' è già impostato a 0.")
                    return True, f"Il tag '{tag_found_name}' è già impostato a 0 (False)."

                nbt_file[tag_found_name] = Byte(0) # type: ignore
                logger.info(f"🏷️✅ Tag '{tag_found_name}' impostato a 0 per '{world_name}'.")
            else:
                logger.warning(f"🏷️❓ Tag '{tag_to_find_camel_case}' o '{tag_to_find_pascal_case}' non trovato in {level_dat_path}.")
                return False, (f"Tag '{tag_to_find_camel_case}' (o simile) non trovato in level.dat. "
                               "Nessuna modifica apportata.")

            with io.BytesIO() as temp_buffer:
                nbt_file.save(temp_buffer, byteorder='little') # type: ignore
                temp_buffer.seek(0)
                header_from_nbtlib = temp_buffer.read(8)
                modified_nbt_data_bytes = temp_buffer.read()
                logger.info(f"⚙️  Dati NBT pronti (no header nbtlib). Len: {len(modified_nbt_data_bytes)}B.")
                logger.debug(f"📄 Header: Originale={original_header}, Nbtlib={header_from_nbtlib}")


            return True, f"Reset del tag '{tag_found_name}' a 0 preparato per '{world_name}'."

        success_processing, message_processing = await asyncio.to_thread(_process_nbt_file)

        if not success_processing:
            return False, message_processing

        if original_header is None or modified_nbt_data_bytes is None:
             logger.error("❌ Errore interno: Header/dati NBT non popolati.")
             return False, "Errore interno durante la preparazione dei dati NBT."

        with open(level_dat_path, "wb") as f_final:
            f_final.write(original_header)
            f_final.write(modified_nbt_data_bytes)

        logger.info(f"💾 Modifiche NBT scritte su {level_dat_path}.")
        return True, message_processing

    except ValueError as ve:
        logger.error(f"❌ Errore valore NBT per {world_name}: {ve}", exc_info=True)
        return False, str(ve)
    except (MalformedFileError, NBTError) as e:
        logger.error(f"❌ Errore NBT ({type(e).__name__}) per {level_dat_path}: {e}", exc_info=True)
        return False, f"Errore NBT durante l'elaborazione di level.dat: {e}"
    except Exception as e:
        logger.error(f"🆘 Errore imprevisto reset flag creativo ({world_name}): {e}", exc_info=True)
        return False, f"Si è verificato un errore imprevisto: {e}"