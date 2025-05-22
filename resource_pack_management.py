# minecraft_telegram_bot/resource_pack_management.py
import os
import json
import zipfile
import requests
import shutil
import uuid # Per generare nomi di file univoci se necessario
import asyncio # Per asyncio.to_thread
from typing import Tuple, Optional, List, Dict, Any

from config import get_logger, WORLD_NAME
from world_management import get_resource_packs_main_folder_path, get_world_specific_resource_packs_json_path

logger = get_logger(__name__)

class ResourcePackError(Exception):
    """Eccezione personalizzata per le operazioni sui resource pack."""
    pass


def _is_valid_url(url: str) -> bool:
    """Validazione URL di base."""
    return url.startswith('http://') or url.startswith('https://')

def _extract_manifest_from_zip(pack_zip_path: str) -> Optional[Dict[str, Any]]:
    """Estrae i dati del manifest da un file zip."""
    try:
        with zipfile.ZipFile(pack_zip_path, 'r') as zf:
            if 'manifest.json' not in zf.namelist():
                logger.error(f"manifest.json non trovato in {pack_zip_path}")
                return None
            with zf.open('manifest.json') as manifest_file:
                return json.load(manifest_file)
    except zipfile.BadZipFile:
        logger.error(f"File zip corrotto o non valido: {pack_zip_path}")
    except json.JSONDecodeError:
        logger.error(f"Errore di decodifica JSON in manifest.json da {pack_zip_path}")
    except Exception as e:
        logger.error(f"Errore imprevisto durante l'estrazione del manifest da {pack_zip_path}: {e}", exc_info=True)
    return None

def _parse_manifest_data(manifest_data: Dict[str, Any], pack_path_for_log: str) -> Tuple[Optional[str], Optional[List[int]], Optional[str]]:
    """Interpreta i dati del manifest estratti."""
    if not manifest_data:
        return None, None, None
        
    header = manifest_data.get('header', {})
    pack_uuid = header.get('uuid')
    version = header.get('version') # Dovrebbe essere un array es. [1, 0, 0]
    name = header.get('name', 'Nome sconosciuto') # Default name

    # Tentativi di trovare un nome più descrittivo se 'name' è generico o mancante
    if name == 'pack.name' or name == 'Nome sconosciuto': # 'pack.name' è un placeholder comune
        modules = manifest_data.get('modules', [])
        if modules and isinstance(modules, list) and len(modules) > 0:
            # La descrizione del primo modulo è spesso usata come nome
            module_description = modules[0].get('description', '').strip()
            if module_description and module_description != 'pack.description':
                name = module_description
            elif name == 'Nome sconosciuto' and pack_path_for_log: # Fallback al nome del file se tutto il resto fallisce
                name = os.path.basename(pack_path_for_log).replace('.zip', '').replace('.mcpack', '')


    if not pack_uuid or not isinstance(pack_uuid, str):
        logger.warning(f"UUID del pacchetto mancante o non valido nel manifest di {pack_path_for_log}")
        return None, version if isinstance(version, list) else None, name
    if not version or not isinstance(version, list) or not all(isinstance(v, int) for v in version):
        logger.warning(f"Versione del pacchetto mancante o non valida ({version}) nel manifest di {pack_path_for_log}")
        # Continua con UUID e nome se la versione non è perfetta, potrebbe essere comunque utile
        return pack_uuid, None, name
    
    logger.info(f"Estratto dal manifest di {pack_path_for_log}: UUID={pack_uuid}, Version={version}, Name={name}")
    return str(pack_uuid), list(version), str(name)


async def download_resource_pack_from_url(url: str, temp_dir: str) -> str:
    """
    Scarica un resource pack da un URL in una directory temporanea.
    Restituisce il percorso al file scaricato.
    """
    if not _is_valid_url(url):
        raise ResourcePackError("URL fornito non valido.")
    try:
        response = await asyncio.to_thread(requests.get, url, stream=True, timeout=30)
        response.raise_for_status()
        content_disposition = response.headers.get('content-disposition')
        filename = None
        if content_disposition:
            parts = content_disposition.split('filename=')
            if len(parts) > 1:
                filename = parts[1].strip('" ')
        if not filename:
            filename = url.split('/')[-1]
            if not filename or '?' in filename: 
                 filename = "downloaded_pack_" + str(uuid.uuid4())[:8]
        if not any(filename.lower().endswith(ext) for ext in ['.zip', '.mcpack']):
            filename += ".zip"
        temp_file_path = os.path.join(temp_dir, filename)
        with open(temp_file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info(f"File scaricato da {url} a {temp_file_path}")
        return temp_file_path
    except requests.exceptions.RequestException as e:
        logger.error(f"Errore durante il download da {url}: {e}")
        raise ResourcePackError(f"Errore di download: {e}")
    except Exception as e:
        logger.error(f"Errore imprevisto durante il download da {url}: {e}", exc_info=True)
        raise ResourcePackError(f"Errore imprevisto durante il download: {e}")


def install_resource_pack_from_file(
    source_file_path: str, 
    original_filename: str
) -> Tuple[str, str, List[int], str]:
    """
    Elabora un file resource pack, lo sposta e estrae i dettagli del manifest.
    Restituisce: (final_pack_path, pack_uuid, pack_version, pack_name)
    """
    resource_packs_folder = get_resource_packs_main_folder_path()
    if not resource_packs_folder:
        raise ResourcePackError("Impossibile determinare la cartella dei resource pack.")
    if not os.path.exists(resource_packs_folder):
        try:
            os.makedirs(resource_packs_folder)
            logger.info(f"Cartella resource_packs creata in {resource_packs_folder}")
        except OSError as e:
            raise ResourcePackError(f"Impossibile creare la cartella dei resource pack {resource_packs_folder}: {e}")

    base, ext = os.path.splitext(original_filename)
    target_filename = base + ".zip" if ext.lower() == '.mcpack' else original_filename
    if not target_filename.lower().endswith(".zip"):
         raise ResourcePackError(f"Formato file non supportato: {original_filename}. Deve essere .zip o .mcpack.")

    destination_path = os.path.join(resource_packs_folder, target_filename)
    if os.path.exists(destination_path):
        logger.warning(f"Il file '{target_filename}' esiste già. Sarà sovrascritto.")
        try:
            os.remove(destination_path)
        except OSError as e:
            raise ResourcePackError(f"Impossibile sovrascrivere '{target_filename}': {e}")

    try:
        shutil.move(source_file_path, destination_path)
        logger.info(f"File '{original_filename}' spostato in '{destination_path}'.")
        
        manifest_data = _extract_manifest_from_zip(destination_path)
        if not manifest_data:
            raise ResourcePackError(f"Impossibile leggere il manifest da {target_filename} dopo l'installazione.")
            
        pack_uuid, pack_version, pack_name = _parse_manifest_data(manifest_data, destination_path)
        if not pack_uuid or not pack_version: # Name può essere un fallback
             # Tenta di usare il nome del file come fallback per il nome del pacchetto se il manifest è problematico
            pack_name_fallback = target_filename.replace('.zip', '')
            logger.warning(f"UUID o versione mancanti nel manifest di {target_filename}. Nome fallback: {pack_name_fallback}")
            if not pack_name: pack_name = pack_name_fallback # Usa solo se pack_name è ancora None o vuoto
            if not pack_uuid: raise ResourcePackError(f"UUID mancante in {target_filename}, impossibile attivare.")
            if not pack_version: pack_version = [0,0,0] # Versione di fallback se non trovata

        return destination_path, pack_uuid, pack_version, pack_name

    except FileNotFoundError:
        raise ResourcePackError("File sorgente del pacchetto non trovato.")
    except Exception as e:
        logger.error(f"Errore durante l'installazione del pacchetto '{original_filename}': {e}", exc_info=True)
        raise ResourcePackError(f"Errore installazione pacchetto: {e}")


def manage_world_resource_packs_json(
    world_name_target: str, 
    pack_uuid_to_add: Optional[str] = None,
    pack_version_to_add: Optional[List[int]] = None,
    pack_uuid_to_remove: Optional[str] = None,
    pack_uuid_to_move: Optional[str] = None,
    new_index_for_move: Optional[int] = None,
    add_at_beginning: bool = False # True per aggiungere all'inizio (priorità più bassa)
) -> List[Dict[str, Any]]:
    """
    Gestisce world_resource_packs.json: aggiunge, rimuove, o sposta un pack.
    Restituisce la lista aggiornata dei pacchetti attivi.
    Ordine di caricamento in Bedrock: il primo pacchetto nella lista JSON ha priorità più bassa,
    l'ultimo ha priorità più alta (appare sopra gli altri).
    """
    if not world_name_target:
        raise ResourcePackError("Nome del mondo non specificato.")
    json_path = get_world_specific_resource_packs_json_path(world_name_target)
    if not json_path:
        raise ResourcePackError(f"Impossibile trovare world_resource_packs.json per '{world_name_target}'.")

    active_packs: List[Dict[str, Any]] = []
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                active_packs = json.load(f)
            if not isinstance(active_packs, list): active_packs = []
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Errore leggendo {json_path}, sarà sovrascritto: {e}")
            active_packs = []
    else:
        logger.info(f"{json_path} non trovato, sarà creato.")
    
    modified = False

    if pack_uuid_to_remove:
        original_len = len(active_packs)
        active_packs = [p for p in active_packs if p.get('pack_id') != pack_uuid_to_remove]
        if len(active_packs) < original_len: modified = True

    if pack_uuid_to_move and new_index_for_move is not None:
        pack_to_move_data = None
        current_index = -1
        for i, p in enumerate(active_packs):
            if p.get('pack_id') == pack_uuid_to_move:
                pack_to_move_data = p
                current_index = i
                break
        if pack_to_move_data and current_index != -1:
            active_packs.pop(current_index)
            # Assicura che new_index_for_move sia nei limiti
            target_index = max(0, min(new_index_for_move, len(active_packs)))
            active_packs.insert(target_index, pack_to_move_data)
            logger.info(f"Pacchetto {pack_uuid_to_move} spostato alla posizione {target_index}.")
            modified = True
        else:
            logger.warning(f"Pacchetto da spostare {pack_uuid_to_move} non trovato tra quelli attivi.")


    if pack_uuid_to_add and pack_version_to_add:
        existing_pack_index = -1
        for i, p in enumerate(active_packs):
            if p.get('pack_id') == pack_uuid_to_add:
                existing_pack_index = i
                break
        new_pack_entry = {"pack_id": pack_uuid_to_add, "version": pack_version_to_add}
        if existing_pack_index != -1: # Pacchetto già presente
            if active_packs[existing_pack_index].get('version') != pack_version_to_add:
                active_packs[existing_pack_index]['version'] = pack_version_to_add
                modified = True
                logger.info(f"Versione del pacchetto {pack_uuid_to_add} aggiornata a {pack_version_to_add}.")
            # Se è già presente con stessa versione e non stiamo specificamente riordinando, non fare nulla
        else: # Nuovo pacchetto
            if add_at_beginning: # Priorità più bassa
                active_packs.insert(0, new_pack_entry)
            else: # Priorità più alta
                active_packs.append(new_pack_entry)
            modified = True
            logger.info(f"Pacchetto {pack_uuid_to_add} aggiunto (priorità {'bassa' if add_at_beginning else 'alta'}).")


    if modified:
        try:
            os.makedirs(os.path.dirname(json_path), exist_ok=True)
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(active_packs, f, indent=2)
            logger.info(f"{json_path} aggiornato.")
        except IOError as e:
            raise ResourcePackError(f"Impossibile scrivere su {json_path}: {e}")
    return active_packs

def list_available_packs() -> List[Dict[str, Any]]:
    """Scansiona la cartella resource_packs e restituisce i dettagli dei pacchetti."""
    packs_folder = get_resource_packs_main_folder_path()
    available_packs = []
    if not packs_folder or not os.path.exists(packs_folder):
        logger.warning(f"Cartella resource_packs ({packs_folder}) non trovata.")
        return []

    for filename in os.listdir(packs_folder):
        if filename.lower().endswith(".zip"):
            file_path = os.path.join(packs_folder, filename)
            manifest_data = _extract_manifest_from_zip(file_path)
            if manifest_data:
                pack_uuid, version, name = _parse_manifest_data(manifest_data, file_path)
                if pack_uuid and version: # Nome è opzionale ma preferito
                    available_packs.append({
                        "uuid": pack_uuid,
                        "version": version,
                        "name": name or filename.replace(".zip", ""), # Fallback a nome file
                        "filename": filename
                    })
                elif pack_uuid: # Caso in cui la versione potrebbe mancare ma UUID c'è
                     available_packs.append({
                        "uuid": pack_uuid,
                        "version": version or [0,0,0], # Fallback versione
                        "name": name or filename.replace(".zip", ""),
                        "filename": filename
                    })


    return available_packs

def get_world_active_packs_with_details(world_name_target: str) -> List[Dict[str, Any]]:
    """Ottiene i pacchetti attivi per un mondo, arricchiti con nome e filename."""
    json_path = get_world_specific_resource_packs_json_path(world_name_target)
    active_packs_from_json = []
    if json_path and os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                active_packs_from_json = json.load(f)
            if not isinstance(active_packs_from_json, list):
                active_packs_from_json = []
        except (json.JSONDecodeError, IOError):
            active_packs_from_json = []
    
    if not active_packs_from_json:
        return []

    all_available_packs = list_available_packs()
    detailed_active_packs = []
    
    for i, active_pack_ref in enumerate(active_packs_from_json):
        pack_id_ref = active_pack_ref.get('pack_id')
        pack_version_ref = active_pack_ref.get('version')
        
        found_details = next((p for p in all_available_packs if p['uuid'] == pack_id_ref), None)
        
        if found_details:
            detailed_active_packs.append({
                "uuid": pack_id_ref,
                "version_in_world_file": pack_version_ref, # Versione come registrata nel mondo
                "name": found_details['name'],
                "filename": found_details['filename'],
                "version_in_manifest": found_details['version'], # Versione dal manifest del file .zip
                "order": i # Ordine 0-based come nel file JSON
            })
        else:
            # Pacchetto attivo nel JSON ma file .zip non trovato o manifest illeggibile
            detailed_active_packs.append({
                "uuid": pack_id_ref,
                "version_in_world_file": pack_version_ref,
                "name": f"Sconosciuto (UUID: {pack_id_ref})",
                "filename": "File non trovato o manifest illeggibile",
                "version_in_manifest": pack_version_ref, # Fallback
                "order": i
            })
            
    return detailed_active_packs
