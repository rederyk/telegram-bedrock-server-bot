import os
import re
import json
import zipfile
import requests
import shutil
import uuid
import asyncio
from typing import Tuple, Optional, List, Dict, Any

from config import get_logger, WORLD_NAME
from world_management import get_resource_packs_main_folder_path, get_world_specific_resource_packs_json_path

logger = get_logger(__name__)

class ResourcePackError(Exception):
    pass


def _is_valid_url(url: str) -> bool:
    return url.startswith('http://') or url.startswith('https://')


def _extract_manifest_from_zip(pack_zip_path: str) -> Optional[Dict[str, Any]]:
    """
    Apre lo .zip, trova manifest.json in qualsiasi sottocartella,
    lo legge come testo e con regex estrae uuid, version e name.
    Ritorna dict compatibile con _parse_manifest_data.
    """
    try:
        with zipfile.ZipFile(pack_zip_path, 'r') as zf:
            path = next((n for n in zf.namelist() if n.lower().endswith('manifest.json')), None)
            if not path:
                logger.error(f"📄❓ manifest.json non trovato in {pack_zip_path}")
                return None
            raw = zf.read(path).decode('utf-8', errors='ignore')

        # estrai via regex
        m_uuid = re.search(r'"uuid"\s*:\s*"([0-9a-fA-F\-]{36})"', raw)
        m_ver = re.search(r'"version"\s*:\s*\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]', raw)
        header = re.search(r'"header"\s*:\s*\{(.*?)\}', raw, flags=re.DOTALL)

        pack_uuid = m_uuid.group(1) if m_uuid else None
        version = [int(m_ver.group(i)) for i in (1, 2, 3)] if m_ver else None

        name = None
        if header:
            m_name = re.search(r'"name"\s*:\s*"([^"}]+)"', header.group(1))
            if m_name:
                name = m_name.group(1)
        if not name:
            name = os.path.splitext(os.path.basename(pack_zip_path))[0]

        # pulizia: rimuovo codici di formattazione Minecraft (§x)
        clean_name = re.sub(r'§.', '', name)

        return {'header': {'uuid': pack_uuid, 'version': version, 'name': clean_name}}

    except zipfile.BadZipFile:
        logger.error(f"📦❌ ZIP corrotto/invalido: {pack_zip_path}")
    except Exception as e:
        logger.error(f"🆘 Errore brutal manifest parse: {e}", exc_info=True)
    return None


def _parse_manifest_data(
    manifest_data: Dict[str, Any],
    pack_path_for_log: str
) -> Tuple[Optional[str], Optional[List[int]], Optional[str]]:
    if not manifest_data:
        return None, None, None

    header = manifest_data.get('header', {})
    pack_uuid = header.get('uuid')
    version = header.get('version')

    # nome grezzo dal manifest
    raw_name = header.get('name', 'Nome sconosciuto')
    # 1) rimuovo codici di formattazione Minecraft (§x)
    name = re.sub(r'§.', '', raw_name)

    # 2) se non ho version dal manifest, cerco “vX.Y.Z” nel nome
    if not version:
        m = re.search(r'v(\d+(?:\.\d+){1,2})', name, flags=re.IGNORECASE)
        if m:
            version = [int(p) for p in m.group(1).split('.')]
            # rimuovo la parte “vX.Y.Z” e parentesi
            name = re.sub(
                r'[\(\[]?\s*v' + re.escape(m.group(1)) + r'[\)\]]?',
                '',
                name,
                flags=re.IGNORECASE
            ).strip()

    # 3) fallback: se nome vuoto, uso filename senza estensione
    if not name:
        name = os.path.splitext(os.path.basename(pack_path_for_log))[0]

    if not pack_uuid or not isinstance(pack_uuid, str):
        logger.warning(f"❓ UUID mancante/invalido in manifest: {pack_path_for_log}")
        return None, version if isinstance(version, list) else None, name
    if not version or not isinstance(version, list) or not all(isinstance(v, int) for v in version):
        logger.warning(f"❓ Versione mancante/invalida ({version}) in manifest: {pack_path_for_log}")
        version = version if isinstance(version, list) else None

    logger.info(f"📄 Estratto manifest {pack_path_for_log}: UUID={pack_uuid}, Ver={version}, Nome={name}")
    return pack_uuid, version, name


async def download_resource_pack_from_url(url: str, temp_dir: str) -> str:
    if not _is_valid_url(url):
        raise ResourcePackError("URL fornito non valido.")
    try:
        response = await asyncio.to_thread(requests.get, url, stream=True, timeout=30)
        response.raise_for_status()
        content_disposition = response.headers.get('content-disposition', '')
        filename = None
        if 'filename=' in content_disposition:
            filename = content_disposition.split('filename=')[-1].strip('" ')
        if not filename:
            filename = os.path.basename(url.split('?')[0]) or f"download_{uuid.uuid4().hex[:8]}"
        if not any(filename.lower().endswith(ext) for ext in ['.zip', '.mcpack']):
            filename += '.zip'
        temp_file_path = os.path.join(temp_dir, filename)
        with open(temp_file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info(f"🔗📦 File scaricato da {url} -> {temp_file_path}")
        return temp_file_path
    except Exception as e:
        logger.error(f"🔗❌ Errore download {url}: {e}")
        raise ResourcePackError(f"Errore download: {e}")


def install_resource_pack_from_file(
    source_file_path: str,
    original_filename: str
) -> Tuple[str, str, List[int], str]:
    resource_packs_folder = get_resource_packs_main_folder_path()
    if not resource_packs_folder:
        raise ResourcePackError("Impossibile determinare la cartella dei resource pack.")
    os.makedirs(resource_packs_folder, exist_ok=True)

    # sposta file nel repository globale
    base, ext = os.path.splitext(original_filename)
    target_filename = base + '.zip' if ext.lower() == '.mcpack' else original_filename
    destination_path = os.path.join(resource_packs_folder, target_filename)
    if os.path.exists(destination_path):
        try:
            os.remove(destination_path)
        except OSError as e:
            raise ResourcePackError(f"Impossibile sovrascrivere '{target_filename}': {e}")

    try:
        shutil.move(source_file_path, destination_path)
        logger.info(f"📦 File '{original_filename}' -> '{destination_path}'")

        # copia anche nella cartella del mondo attivo
        world_json = get_world_specific_resource_packs_json_path(WORLD_NAME)
        if world_json:
            world_res_dir = os.path.join(os.path.dirname(world_json), 'resource_packs')
            os.makedirs(world_res_dir, exist_ok=True)
            shutil.copy(destination_path, os.path.join(world_res_dir, os.path.basename(destination_path)))
            logger.info(f"📦 Copiato '{destination_path}' in world resource_packs: {world_res_dir}")

        manifest_data = _extract_manifest_from_zip(destination_path)
        if not manifest_data:
            raise ResourcePackError(f"Impossibile leggere manifest da {target_filename} dopo installazione.")

        pack_uuid, pack_version, pack_name = _parse_manifest_data(manifest_data, destination_path)
        if not pack_uuid or not pack_version:
            pack_name_fallback = target_filename.replace('.zip', '')
            if not pack_name_fallback:
                pack_name_fallback = base
            if not pack_uuid:
                raise ResourcePackError(f"UUID mancante in {target_filename}, impossibile attivare.")
            if not pack_version:
                pack_version = [0, 0, 0]

        return destination_path, pack_uuid, pack_version, pack_name

    except FileNotFoundError:
        raise ResourcePackError("File sorgente del pacchetto non trovato.")
    except Exception as e:
        logger.error(f"🆘 Errore installazione RP '{original_filename}': {e}", exc_info=True)
        raise ResourcePackError(f"Errore installazione pacchetto: {e}")


def manage_world_resource_packs_json(
    world_name_target: str,
    pack_uuid_to_add: Optional[str] = None,
    pack_version_to_add: Optional[List[int]] = None,
    pack_uuid_to_remove: Optional[str] = None,
    pack_uuid_to_move: Optional[str] = None,
    new_index_for_move: Optional[int] = None,
    add_at_beginning: bool = False
) -> List[Dict[str, Any]]:
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
            if not isinstance(active_packs, list):
                active_packs = []
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"📄⚠️ Errore lettura {json_path}, sarà sovrascritto: {e}")
            active_packs = []
    else:
        logger.info(f"📄 {json_path} non trovato, sarà creato.")

    modified = False

    if pack_uuid_to_remove:
        original_len = len(active_packs)
        active_packs = [p for p in active_packs if p.get('pack_id') != pack_uuid_to_remove]
        if len(active_packs) < original_len:
            modified = True

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
            target_index = max(0, min(new_index_for_move, len(active_packs)))
            active_packs.insert(target_index, pack_to_move_data)
            logger.info(f"📦↕️ RP {pack_uuid_to_move} spostato a pos {target_index}. usa /restartserver per applicare")
            modified = True
        else:
            logger.warning(f"📦❓ RP da spostare {pack_uuid_to_move} non attivo.")

    if pack_uuid_to_add and pack_version_to_add:
        existing_pack_index = -1
        for i, p in enumerate(active_packs):
            if p.get('pack_id') == pack_uuid_to_add:
                existing_pack_index = i
                break
        new_pack_entry = {"pack_id": pack_uuid_to_add, "version": pack_version_to_add}
        if existing_pack_index != -1:
            if active_packs[existing_pack_index].get('version') != pack_version_to_add:
                active_packs[existing_pack_index]['version'] = pack_version_to_add
                modified = True
                logger.info(f"📦🔄 Versione RP {pack_uuid_to_add} aggiornata a {pack_version_to_add}.")
        else:
            if add_at_beginning:
                active_packs.insert(0, new_pack_entry)
            else:
                active_packs.append(new_pack_entry)
            modified = True
            logger.info(f"📦➕ RP {pack_uuid_to_add} aggiunto (priorità {'bassa' if add_at_beginning else 'alta'}).")

    if modified:
        try:
            os.makedirs(os.path.dirname(json_path), exist_ok=True)
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(active_packs, f, indent=2)
            logger.info(f"💾 {json_path} aggiornato.")
        except IOError as e:
            raise ResourcePackError(f"Impossibile scrivere su {json_path}: {e}")

    return active_packs


def list_available_packs() -> List[Dict[str, Any]]:
    packs_folder = get_resource_packs_main_folder_path()
    available_packs = []
    if not packs_folder or not os.path.exists(packs_folder):
        logger.warning(f"📦❓ Cartella resource_packs ({packs_folder}) non trovata.")
        return []

    for filename in os.listdir(packs_folder):
        if filename.lower().endswith(".zip"):
            file_path = os.path.join(packs_folder, filename)
            manifest_data = _extract_manifest_from_zip(file_path)
            if manifest_data:
                pack_uuid, version, name = _parse_manifest_data(manifest_data, file_path)
                if pack_uuid and version:
                    available_packs.append({
                        "uuid": pack_uuid,
                        "version": version,
                        "name": name or filename.replace(".zip", ""),
                        "filename": filename
                    })
                elif pack_uuid:
                    available_packs.append({
                        "uuid": pack_uuid,
                        "version": version or [0, 0, 0],
                        "name": name or filename.replace(".zip", ""),
                        "filename": filename
                    })
    return available_packs


def get_world_active_packs_with_details(world_name_target: str) -> List[Dict[str, Any]]:
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
                "version_in_world_file": pack_version_ref,
                "name": found_details['name'],
                "filename": found_details['filename'],
                "version_in_manifest": found_details['version'],
                "order": i
            })
        else:
            detailed_active_packs.append({
                "uuid": pack_id_ref,
                "version_in_world_file": pack_version_ref,
                "name": f"Sconosciuto (UUID: {pack_id_ref})",
                "filename": "File non trovato o manifest illeggibile",
                "version_in_manifest": pack_version_ref,
                "order": i
            })
    return detailed_active_packs
