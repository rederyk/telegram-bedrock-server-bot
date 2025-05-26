#!/usr/bin/env python3
import argparse
import math
import logging
import os
from typing import Tuple, Optional

# Importazioni Amulet
try:
    import amulet
    from amulet.api.level import World
    from amulet.api.data_types import Dimension, BlockCoordinates
    from amulet.api.selection import SelectionBox
except ImportError as e:
    print(f"Errore: Amulet-Core non trovato: {e}")
    print("Installa con: pip install amulet-core amulet-nbt")
    exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(asctime)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

def parse_coordinates(coords_str: str) -> Optional[Tuple[float, float, float]]:
    """Converte una stringa "x,y,z" in una tupla di float."""
    try:
        parts = coords_str.split(',')
        if len(parts) == 3:
            return float(parts[0]), float(parts[1]), float(parts[2])
        else:
            logger.error(f"Formato coordinate non valido: '{coords_str}'. Usare x,y,z.")
            return None
    except ValueError:
        logger.error(f"Coordinate non numeriche: '{coords_str}'.")
        return None

def get_structure_bounds(structure_path: str) -> Tuple[SelectionBox, str]:
    """
    Carica la struttura e ottiene i suoi bounds originali.
    Restituisce i bounds e la dimensione principale.
    """
    logger.info(f"Analisi struttura: {structure_path}")
    
    structure_level = amulet.load_level(structure_path)
    
    try:
        dimensions = structure_level.dimensions
        if not dimensions:
            raise ValueError("Struttura non contiene dimensioni valide.")
            
        structure_dimension = dimensions[0]
        logger.debug(f"Dimensione struttura: {structure_dimension}")
        
        # Ottieni i bounds della struttura
        bounds = structure_level.bounds(structure_dimension)
        logger.info(f"Bounds struttura originali:")
        logger.info(f"  X: {bounds.min_x} → {bounds.max_x} (larghezza: {bounds.max_x - bounds.min_x})")
        logger.info(f"  Y: {bounds.min_y} → {bounds.max_y} (altezza: {bounds.max_y - bounds.min_y})")
        logger.info(f"  Z: {bounds.min_z} → {bounds.max_z} (profondità: {bounds.max_z - bounds.min_z})")
        logger.info(f"Origine struttura: ({bounds.min_x}, {bounds.min_y}, {bounds.min_z})")
        
        return bounds, structure_dimension
        
    finally:
        structure_level.close()

def calculate_placement_offset(structure_bounds: SelectionBox, target_coords: Tuple[float, float, float], 
                              placement_mode: str = "origin") -> Tuple[int, int, int]:
    """
    Calcola dove dire ad Amulet di fare il paste per ottenere il posizionamento desiderato.
    IMPORTANTE: Amulet usa il centro della struttura come riferimento per il paste,
    quindi dobbiamo compensare questo comportamento.
    
    Args:
        structure_bounds: Bounds originali della struttura
        target_coords: Coordinate dove vogliamo posizionare la struttura
        placement_mode: Modalità di posizionamento
            - "origin": posiziona l'origine della struttura alle coordinate target
            - "center": centra la struttura sulle coordinate target
            - "bottom_center": centra XZ, origine Y
    
    Returns:
        Coordinate da passare ad Amulet per il paste
    """
    target_x, target_y, target_z = target_coords
    
    # CORREZIONE: Usa divisione float per calcolo preciso del centro
    structure_center_x = (structure_bounds.min_x + structure_bounds.max_x) / 2.0
    structure_center_y = (structure_bounds.min_y + structure_bounds.max_y) / 2.0
    structure_center_z = (structure_bounds.min_z + structure_bounds.max_z) / 2.0
    
    logger.info(f"Centro struttura (riferimento Amulet): ({structure_center_x}, {structure_center_y}, {structure_center_z})")
    
    if placement_mode == "origin":
        # Vogliamo che l'origine sia alle coordinate target
        # Ma Amulet posiziona il centro, quindi dobbiamo dirgli di posizionare
        # il centro alle coordinate: target + (centro - origine)
        
        offset_from_origin_to_center_x = structure_center_x - structure_bounds.min_x
        offset_from_origin_to_center_y = structure_center_y - structure_bounds.min_y
        offset_from_origin_to_center_z = structure_center_z - structure_bounds.min_z
        
        paste_x = target_x + offset_from_origin_to_center_x
        paste_y = target_y + offset_from_origin_to_center_y
        paste_z = target_z + offset_from_origin_to_center_z
        
        logger.info(f"Modalità: ORIGINE → coordinate target")
        logger.info(f"Vogliamo origine a: ({target_x}, {target_y}, {target_z})")
        logger.info(f"Offset origine→centro: ({offset_from_origin_to_center_x:.1f}, {offset_from_origin_to_center_y:.1f}, {offset_from_origin_to_center_z:.1f})")
        logger.info(f"Quindi diciamo ad Amulet di posizionare il centro a: ({paste_x:.1f}, {paste_y:.1f}, {paste_z:.1f})")
        
    elif placement_mode == "center":
        # Vogliamo che il centro sia alle coordinate target
        # Perfetto, è quello che fa Amulet di default
        paste_x = target_x
        paste_y = target_y
        paste_z = target_z
        
        logger.info(f"Modalità: CENTRO → coordinate target")
        logger.info(f"Posizionamento diretto del centro a: ({target_x}, {target_y}, {target_z})")
        
    elif placement_mode == "bottom_center":
        # Vogliamo centro su XZ, ma origine su Y
        paste_x = target_x  # Centro su X
        paste_y = target_y + (structure_center_y - structure_bounds.min_y)  # Origine su Y
        paste_z = target_z  # Centro su Z
        
        logger.info(f"Modalità: CENTRO XZ, ORIGINE Y → coordinate target")
        logger.info(f"Centro XZ, offset Y: {structure_center_y - structure_bounds.min_y:.1f}")
        
    else:
        raise ValueError(f"Modalità posizionamento non valida: {placement_mode}")
    
    # CORREZIONE: Arrotonda solo alla fine
    final_coords = (int(round(paste_x)), int(round(paste_y)), int(round(paste_z)))
    logger.info(f"Coordinate paste per Amulet: {final_coords}")
    
    return final_coords

def place_structure(
    world_path: str,
    structure_path: str,
    target_coords_str: str,
    orientation: str = "east",
    target_dimension_name: str = "overworld",
    placement_mode: str = "origin"
):
    """
    Incolla una struttura alle coordinate specificate.
    """
    target_coords = parse_coordinates(target_coords_str)
    if not target_coords:
        return

    if not os.path.exists(world_path):
        logger.error(f"Mondo non trovato: {world_path}")
        return
    if not os.path.exists(structure_path):
        logger.error(f"Struttura non trovata: {structure_path}")
        return

    # Fase 1: Analizza la struttura
    try:
        structure_bounds, structure_dimension = get_structure_bounds(structure_path)
    except Exception as e:
        logger.error(f"Errore analisi struttura: {e}")
        return

    # Fase 2: Calcola dove posizionare la struttura
    try:
        paste_coords = calculate_placement_offset(structure_bounds, target_coords, placement_mode)
    except Exception as e:
        logger.error(f"Errore calcolo posizionamento: {e}")
        return

    # Fase 3: Carica il mondo di destinazione
    logger.info(f"Caricamento mondo: {world_path}")
    try:
        world = amulet.load_level(world_path)
    except Exception as e:
        logger.error(f"Errore caricamento mondo: {e}")
        return
    
    # Trova la dimensione corretta
    actual_dimension = None
    dimension_variants = [
        target_dimension_name, 
        f"minecraft:{target_dimension_name}",
        target_dimension_name.replace("minecraft:", "")
    ]
    
    for dim_name in dimension_variants:
        if dim_name in world.dimensions:
            actual_dimension = dim_name
            break
    
    if actual_dimension is None:
        if world.dimensions:
            actual_dimension = list(world.dimensions.keys())[0]
            logger.warning(f"Dimensione '{target_dimension_name}' non trovata. Uso: '{actual_dimension}'")
        else:
            logger.error("Nessuna dimensione trovata.")
            world.close()
            return

    logger.info(f"Dimensione destinazione: {actual_dimension}")

    # Gestione rotazione
    orientation_angles = {
        "north": 0.0,
        "east": 90.0,
        "south": 180.0,
        "west": 270.0
    }
    
    if orientation.lower() not in orientation_angles:
        logger.warning(f"Orientamento '{orientation}' non valido. Uso 'east'.")
        orientation = "east"
    
    rotation_degrees = orientation_angles[orientation.lower()]

    # Fase 4: Carica la struttura per il paste
    logger.info(f"Preparazione paste...")
    try:
        structure_level = amulet.load_level(structure_path)
        structure_selection = structure_level.selection_bounds
        
        if not structure_selection or len(structure_selection) == 0:
            logger.error("Struttura non contiene selezioni valide.")
            structure_level.close()
            world.close()
            return
            
    except Exception as e:
        logger.error(f"Errore caricamento struttura per paste: {e}")
        world.close()
        return

    # Fase 5: Esegui il paste
    target_block_coords: BlockCoordinates = (
        paste_coords[0],
        paste_coords[1],
        paste_coords[2]
    )
    
    logger.info(f"=== RIEPILOGO PASTE ===")
    logger.info(f"Coordinate target richieste: {target_coords}")
    logger.info(f"Modalità posizionamento: {placement_mode}")
    logger.info(f"Coordinate paste effettive: {target_block_coords}")
    logger.info(f"Orientamento: {orientation.capitalize()} ({rotation_degrees}°)")
    logger.info("=======================")

    try:
        if rotation_degrees != 0.0:
            # Paste con rotazione
            rotation_radians = (0.0, math.radians(rotation_degrees), 0.0)
            
            world.paste(
                src_structure=structure_level,
                src_dimension=structure_dimension,
                src_selection=structure_selection,
                dst_dimension=actual_dimension,
                location=target_block_coords,
                scale=(1.0, 1.0, 1.0),
                rotation=rotation_radians,
                include_blocks=True,
                include_entities=True,
                skip_blocks=(),
                copy_chunk_not_exist=False
            )
        else:
            # Paste semplice senza rotazione
            world.paste(
                src_structure=structure_level,
                src_dimension=structure_dimension,
                src_selection=structure_selection,
                dst_dimension=actual_dimension,
                location=target_block_coords,
                include_blocks=True,
                include_entities=True
            )
        
        logger.info("✅ Paste completato con successo!")
        logger.info("Salvataggio mondo...")
        world.save()
        logger.info("✅ Mondo salvato!")

    except Exception as e:
        logger.error(f"❌ Errore durante il paste: {e}")
        # Prova un paste semplice come fallback
        if rotation_degrees != 0.0:
            try:
                logger.info("Tentativo paste senza rotazione...")
                world.paste(
                    src_structure=structure_level,
                    src_dimension=structure_dimension,
                    src_selection=structure_selection,
                    dst_dimension=actual_dimension,
                    location=target_block_coords,
                    include_blocks=True,
                    include_entities=True
                )
                world.save()
                logger.info("✅ Paste semplice completato!")
            except Exception as e2:
                logger.error(f"❌ Paste fallito completamente: {e2}")
        
    finally:
        try:
            structure_level.close()
        except:
            pass
        world.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Incolla una struttura Minecraft alle coordinate specificate usando l'origine della struttura."
    )
    parser.add_argument("world_path", help="Percorso cartella mondo Minecraft")
    parser.add_argument("structure_path", help="Percorso file struttura (.mcstructure, .schematic)")
    parser.add_argument("coordinates", help="Coordinate destinazione 'x,y,z'")
    parser.add_argument(
        "--orient", type=str, default="east", 
        choices=["north", "south", "east", "west"],
        help="Orientamento struttura (default: east)"
    )
    parser.add_argument(
        "--dimension", type=str, default="overworld",
        help="Dimensione destinazione (default: overworld)"
    )
    parser.add_argument(
        "--mode", type=str, default="origin",
        choices=["origin", "center", "bottom_center"],
        help="Modalità posizionamento: origin=origine struttura, center=centro, bottom_center=centro XZ+origine Y (default: origin)"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Output dettagliato"
    )

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    logger.warning("ATTENZIONE: Questo script modificherà il mondo!")
    logger.warning("Fai un BACKUP prima di procedere!")
    logger.warning("Il server Minecraft DEVE essere spento!")
    
    place_structure(
        args.world_path,
        args.structure_path,
        args.coordinates,
        args.orient,
        args.dimension,
        args.mode
    )