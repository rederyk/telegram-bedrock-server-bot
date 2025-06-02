# minecraft_telegram_bot/armor_stand_handlers.py
import asyncio
import re
import os
import subprocess
import json  # ADD THIS IMPORT - This was missing!
import shutil
import uuid

from config import get_logger
# hologram_handlers imports are removed as the function using them is removed.

logger = get_logger(__name__)

def copy_world(source_path: str) -> str:
    """Copies the world to a temporary directory and returns the path to the copy."""
    temp_dir = os.path.join(os.path.dirname(source_path), str(uuid.uuid4()))
    try:
        shutil.copytree(source_path, temp_dir)
        logger.info(f"World copied to temporary directory: {temp_dir}")
        return temp_dir
    except Exception as e:
        logger.error(f"Failed to copy world: {e}")
        return ""

async def remove_world_copy(world_copy_path: str) -> None:
    """Removes the world copy."""
    try:
        shutil.rmtree(world_copy_path)
        logger.info(f"World copy removed from: {world_copy_path}")
    except Exception as e:
        logger.error(f"Failed to remove world copy: {e}")

# --- Constants for search_armorstand.py script ---
# Assumes this handler file (armor_stand_handlers.py) is in the project root.
_PROJECT_ROOT = os.path.dirname(__file__)
SEARCH_SCRIPT_DIR = os.path.abspath(os.path.join(_PROJECT_ROOT, "importBuild", "schem_to_mc_amulet"))
VENV_PYTHON_EXECUTABLE = os.path.join(SEARCH_SCRIPT_DIR, "venv", "bin", "python")
SEARCH_ARMORSTAND_SCRIPT = os.path.join(SEARCH_SCRIPT_DIR, "search_armorstand.py")
# --- End Constants ---

async def get_armor_stand_data_from_script(world_folder_name: str, coordinates_str: str) -> list[dict]:
    """
    Runs the search_armorstand.py script and parses its JSON output to find armor stand data.

    Args:
        world_folder_name: The name of the world folder (e.g., "Bedrock-piombino").
        coordinates_str: The coordinates string "x,y,z".

    Returns:
        A list of dictionaries, where each dictionary contains data for a found armor stand.
        Example: {
            "id": "minecraft:armor_stand", 
            "position": [x,y,z], 
            "yaw": Y, 
            "pitch": P, 
            "direction": "DIRECTION_STR",
            "custom_name": "Name or None",
            "marker": True/False,
            "invisible": True/False
        }
        Returns an empty list if no armor stands are found or an error occurs.
    """
    logger.info(f"Attempting to get armor stand data for world '{world_folder_name}' at coords '{coordinates_str}' using script.")

    # Use the same world path resolution as the debug call
    try:
        from world_management import get_world_directory_path
        world_dir_path_obj = get_world_directory_path(world_folder_name)
        if not world_dir_path_obj or not os.path.exists(world_dir_path_obj):
            logger.error(f"World directory for '{world_folder_name}' not found via get_world_directory_path")
            return []
        world_path_arg = str(world_dir_path_obj)
        logger.info(f"Resolved world path: {world_path_arg}")
    except Exception as e:
        logger.error(f"Failed to resolve world path for '{world_folder_name}': {e}")
        # Fallback to relative path
        world_path_arg = f"../../bds_data/worlds/{world_folder_name}"
        logger.warning(f"Using fallback relative path: {world_path_arg}")

    # Copy the world
    world_copy_path = copy_world(world_path_arg)
    if not world_copy_path:
        return []
    
    cmd = [
        VENV_PYTHON_EXECUTABLE,
        SEARCH_ARMORSTAND_SCRIPT,
        world_copy_path,
        coordinates_str
    ]

    logger.info(f"Executing command: {' '.join(cmd)} in CWD: {SEARCH_SCRIPT_DIR}")
    logger.warning("Note: If the script requires sudo, this execution will likely fail unless permissions are adjusted or sudoers configured for NOPASSWD execution by the bot user.")

    armor_stands_data = []
    try:
        # Ensure the script and python executable exist before trying to run
        if not os.path.exists(VENV_PYTHON_EXECUTABLE):
            logger.error(f"Python executable not found: {VENV_PYTHON_EXECUTABLE}")
            return []
        if not os.path.exists(SEARCH_ARMORSTAND_SCRIPT):
            logger.error(f"Armor stand script not found: {SEARCH_ARMORSTAND_SCRIPT}")
            return []
        if not os.path.isdir(SEARCH_SCRIPT_DIR):
            logger.error(f"Script directory not found: {SEARCH_SCRIPT_DIR}")
            return []

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=SEARCH_SCRIPT_DIR
        )
        stdout, stderr = await process.communicate()

        output = stdout.decode('utf-8', errors='ignore')
        error_output = stderr.decode('utf-8', errors='ignore')

        # Log dettagliato per debugging
        logger.debug(f"Script return code: {process.returncode}")
        logger.debug(f"Script stdout length: {len(output)} chars")
        logger.debug(f"Script stderr length: {len(error_output)} chars")

        if process.returncode != 0:
            logger.error(f"Script execution failed with code {process.returncode}.")
            logger.error(f"Stderr: {error_output}")
            return []
        
        # Il log dettagliato va su stderr, l'output JSON va su stdout
        if error_output:
            logger.debug("Script debugging info available in stderr (this is normal)")
        
        # Parse JSON output from stdout
        if output.strip():
            try:
                armor_stands_data = json.loads(output.strip())
                logger.info(f"Successfully parsed {len(armor_stands_data)} armor stand(s) from JSON output.")
                
                # Log dei risultati trovati
                for i, stand_data in enumerate(armor_stands_data):
                    logger.info(f"  [{i}] Found: ID={stand_data.get('id', 'N/A')}, "
                               f"Position={stand_data.get('position', 'N/A')}, "
                               f"Direction={stand_data.get('direction', 'N/A')}, "
                               f"Yaw={stand_data.get('yaw', 'N/A')}")
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON from script output: {e}")
                logger.error(f"Raw stdout (first 500 chars): {output[:500]}")
                return []
        else:
            logger.info("Script produced no JSON output - no armor stands found.")
            armor_stands_data = []

    except FileNotFoundError:
        logger.error(f"Script or Python executable not found. Command: {' '.join(cmd)}. Check paths VENV_PYTHON_EXECUTABLE and SEARCH_ARMORSTAND_SCRIPT.")
        return []
    except Exception as e:
        logger.error(f"An error occurred while running/parsing armor stand script: {e}", exc_info=True)
        return []
    finally:
        await remove_world_copy(world_copy_path)

    return armor_stands_data
