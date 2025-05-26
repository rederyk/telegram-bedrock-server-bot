#!/usr/bin/env python3
"""
Divide un file .mcstructure o .schematic in due parti uguali se contiene più di 5000 blocchi non-aria
E se la struttura contiene almeno 4 chunk.
La divisione avviene automaticamente sull'asse più lungo tra X e Z (evitando Y=altezza).
Se specificato dall'utente, può dividere anche sull'asse Y.
I file risultanti saranno salvati come .schematic con suffisso *part1 e *part2 e il conteggio dei blocchi.
"""
import argparse
import sys
import os
import logging
from amulet import load_level
from amulet.api.block import Block
from amulet.api.selection import SelectionBox, SelectionGroup
from amulet.level.formats.schematic import SchematicFormatWrapper
from typing import Tuple, List

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s"
)

DEFAULT_THRESHOLD = 6000
MIN_CHUNKS_FOR_SPLIT = 4
AIR_BLOCK = Block("minecraft", "air")

def format_block_count(count: int) -> str:
    """
    Formatta il conteggio dei blocchi usando abbreviazioni K, M, B per numeri grandi.
    """
    if count >= 1_000_000_000:
        return f"{count / 1_000_000_000:.1f}B".rstrip('0').rstrip('.')
    elif count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M".rstrip('0').rstrip('.')
    elif count >= 1_000:
        return f"{count / 1_000:.1f}K".rstrip('0').rstrip('.')
    else:
        return str(count)

def count_chunks(level, dimension) -> int:
    """
    Conta il numero di chunk nella struttura.
    """
    chunk_coords = list(level.get_chunk_boxes(dimension))
    chunk_count = len(chunk_coords)
    logging.info(f"Numero di chunk nella struttura: {chunk_count}")
    return chunk_count

def count_non_air_blocks(level, dimension) -> int:
    """
    Conta i blocchi non-aria in una dimensione del livello.
    """
    count = 0
    chunk_coords = list(level.get_chunk_boxes(dimension))

    logging.info(f"Conteggio blocchi in {len(chunk_coords)} chunk...")

    for i, (chunk, box) in enumerate(chunk_coords):
        if i % 10 == 0:  # Log ogni 10 chunk per non intasare
            logging.debug(f"Elaborazione chunk {i+1}/{len(chunk_coords)}")

        # Ottieni tutti i blocchi del chunk
        for x in range(box.min_x, box.max_x):
            for y in range(box.min_y, box.max_y):
                for z in range(box.min_z, box.max_z):
                    try:
                        block = level.get_block(x, y, z, dimension)
                        if block != AIR_BLOCK:
                            count += 1
                    except:
                        # Ignora errori per blocchi fuori bounds
                        pass

    return count

def count_non_air_blocks_in_selection(level, dimension, selection_box: SelectionBox) -> int:
    """
    Conta i blocchi non-aria in una specifica selezione.
    """
    count = 0

    for x in range(selection_box.min_x, selection_box.max_x):
        for y in range(selection_box.min_y, selection_box.max_y):
            for z in range(selection_box.min_z, selection_box.max_z):
                try:
                    block = level.get_block(x, y, z, dimension)
                    if block != AIR_BLOCK:
                        count += 1
                except:
                    # Ignora errori per blocchi fuori bounds
                    pass

    return count

def get_structure_bounds(level, dimension) -> Tuple[int, int, int, int, int, int]:
    """
    Restituisce i bounds della struttura (min_x, min_y, min_z, max_x, max_y, max_z).
    """
    bounds = level.bounds(dimension)
    return (bounds.min_x, bounds.min_y, bounds.min_z,
            bounds.max_x, bounds.max_y, bounds.max_z)

def choose_optimal_axis(min_x: int, min_y: int, min_z: int,
                       max_x: int, max_y: int, max_z: int,
                       user_specified_axis: str = None) -> str:
    """
    Sceglie l'asse ottimale per la divisione.
    Se l'utente ha specificato un asse, lo usa.
    Altrimenti sceglie il più lungo tra X e Z (evitando Y=altezza).
    """
    if user_specified_axis:
        logging.info(f"Asse specificato dall'utente: {user_specified_axis.upper()}")
        return user_specified_axis.lower()

    # Calcola le dimensioni
    x_size = max_x - min_x
    y_size = max_y - min_y
    z_size = max_z - min_z

    logging.info(f"Dimensioni struttura: X={x_size}, Y={y_size} (altezza), Z={z_size}")

    # Sceglie tra X e Z (quello più lungo), evitando Y
    if x_size >= z_size:
        chosen_axis = "x"
        logging.info(f"Asse scelto automaticamente: X (dimensione {x_size} ≥ Z {z_size})")
    else:
        chosen_axis = "z"
        logging.info(f"Asse scelto automaticamente: Z (dimensione {z_size} > X {x_size})")

    if y_size > max(x_size, z_size):
        logging.info(f"Nota: L'altezza Y ({y_size}) è maggiore, ma viene evitata automaticamente.")
        logging.info("Usa --axis y se vuoi dividere verticalmente.")

    return chosen_axis

def create_part_path(original_path: str, part_num: int, block_count: int = None) -> str:
    """
    Crea il percorso per una parte cambiando estensione in .schematic e aggiungendo suffisso con conteggio blocchi.
    """
    base = os.path.splitext(original_path)[0]

    if block_count is not None:
        count_str = format_block_count(block_count)
        return f"{base}_part{part_num}_{count_str}blocks.schematic"
    else:
        return f"{base}_part{part_num}.schematic"

def save_selection_as_schematic(
    original_level,
    dimension,
    selection_area: SelectionBox,
    output_path: str
):
    """
    Salva una selezione come file .schematic usando extract_structure di Amulet.
    """
    logging.info(f"Salvataggio selezione come schematic: {output_path}")
    logging.debug(f"Area di selezione: {selection_area}")

    # Calcola le dimensioni della selezione
    width = selection_area.max_x - selection_area.min_x
    height = selection_area.max_y - selection_area.min_y
    depth = selection_area.max_z - selection_area.min_z

    logging.info(f"Dimensioni selezione: {width}x{height}x{depth}")

    # Assicurati che il percorso sia assoluto e crea la directory se necessario
    abs_output_path = os.path.abspath(output_path)
    output_dir = os.path.dirname(abs_output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    logging.debug(f"Percorso assoluto output: {abs_output_path}")

    try:
        # Crea un SelectionGroup dalla SelectionBox
        selection_group = SelectionGroup([selection_area])

        # Estrai la struttura usando extract_structure
        logging.debug("Estrazione struttura...")
        extracted_structure = original_level.extract_structure(selection_group, dimension)

        # Crea un wrapper per il file schematic di output
        logging.debug("Creazione wrapper schematic...")
        schematic_wrapper = SchematicFormatWrapper(abs_output_path)

        # Apri il wrapper per la scrittura
        logging.debug("Apertura wrapper per la scrittura...")
        schematic_wrapper.create_and_open(
            platform="java",
            version=(1, 12, 2),
            bounds=selection_group,
            overwrite=True
        )

        # Salva la struttura estratta come schematic
        logging.debug("Salvataggio come schematic...")
        extracted_structure.save(wrapper=schematic_wrapper)

        # Chiudi il wrapper
        schematic_wrapper.close()

        logging.info(f"Schematic salvato con successo: {abs_output_path}")

    except Exception as e:
        logging.error(f"Errore durante il salvataggio: {e}")
        # Prova un approccio alternativo con save_iter per debugging
        try:
            logging.info("Tentativo con save_iter...")
            schematic_wrapper = SchematicFormatWrapper(abs_output_path)
            schematic_wrapper.create_and_open(
                platform="java",
                version=(1, 12, 2),
                bounds=selection_group,
                overwrite=True
            )
            for progress in extracted_structure.save_iter(wrapper=schematic_wrapper):
                if int(progress * 100) % 20 == 0:  # Log ogni 20%
                    logging.debug(f"Progresso salvataggio: {progress*100:.1f}%")
            schematic_wrapper.close()
            logging.info("Salvataggio completato con successo usando save_iter")
        except Exception as e2:
            logging.error(f"Anche save_iter è fallito: {e2}")
            try:
                schematic_wrapper.close()
            except:
                pass
            raise e

def split_structure(
    input_path: str,
    split_axis: str = None,
    threshold: int = DEFAULT_THRESHOLD,
    min_chunks: int = MIN_CHUNKS_FOR_SPLIT
) -> List[str]:
    """
    Divide un .mcstructure o .schematic in due parti se supera la soglia di blocchi non-aria
    E se contiene almeno min_chunks chunk.
    Se split_axis è None, sceglie automaticamente l'asse più lungo tra X e Z.
    """
    # Verifica estensione file
    ext = os.path.splitext(input_path)[1].lower()
    if ext not in ['.mcstructure', '.schematic']:
        raise ValueError(f"Formato file non supportato: {ext}. Usa .mcstructure o .schematic")

    # Carica il file
    logging.info(f"Caricamento struttura: {input_path}")
    level = load_level(input_path)

    try:
        # Ottieni le dimensioni disponibili
        dimensions = level.dimensions
        if not dimensions:
            raise ValueError("Nessuna dimensione trovata nel file")

        dimension = dimensions[0]
        logging.info(f"Usando dimensione: {dimension}")

        # Conta i chunk
        chunk_count = count_chunks(level, dimension)
        
        # Conta i blocchi non-aria
        logging.info("Conteggio blocchi non-aria...")
        non_air_count = count_non_air_blocks(level, dimension)
        logging.info(f"Blocchi non-aria trovati: {non_air_count}")

        # Controlla entrambe le condizioni: soglia blocchi e numero minimo di chunk
        if non_air_count <= threshold:
            logging.info(f"Il file ha {non_air_count} blocchi (≤ {threshold}), non serve dividere")
            return [input_path]
        
        if chunk_count < min_chunks:
            logging.info(f"Il file ha solo {chunk_count} chunk (< {min_chunks}), troppo piccolo per essere diviso")
            logging.info(f"Anche se contiene {non_air_count} blocchi (> {threshold}), evito la divisione")
            return [input_path]

        logging.info(f"Il file ha {non_air_count} blocchi (> {threshold}) e {chunk_count} chunk (≥ {min_chunks})")
        logging.info("Procedo con la divisione")

        # Ottieni i bounds della struttura
        min_x, min_y, min_z, max_x, max_y, max_z = get_structure_bounds(level, dimension)
        logging.info(f"Bounds struttura: X({min_x}→{max_x}) Y({min_y}→{max_y}) Z({min_z}→{max_z})")

        # Scegli l'asse ottimale
        chosen_axis = choose_optimal_axis(min_x, min_y, min_z, max_x, max_y, max_z, split_axis)

        # Calcola il punto di divisione
        if chosen_axis == "x":
            split_point = (min_x + max_x) // 2
            logging.info(f"Divisione lungo X al punto: {split_point}")

            # Definisci le due aree senza overlap per evitare duplicati
            area1 = SelectionBox((min_x, min_y, min_z), (split_point, max_y, max_z))
            area2 = SelectionBox((split_point, min_y, min_z), (max_x, max_y, max_z))

        elif chosen_axis == "y":
            split_point = (min_y + max_y) // 2
            logging.info(f"Divisione lungo Y (altezza) al punto: {split_point}")

            area1 = SelectionBox((min_x, min_y, min_z), (max_x, split_point, max_z))
            area2 = SelectionBox((min_x, split_point, min_z), (max_x, max_y, max_z))

        elif chosen_axis == "z":
            split_point = (min_z + max_z) // 2
            logging.info(f"Divisione lungo Z al punto: {split_point}")

            area1 = SelectionBox((min_x, min_y, min_z), (max_x, max_y, split_point))
            area2 = SelectionBox((min_x, min_y, split_point), (max_x, max_y, max_z))

        else:
            raise ValueError(f"Asse non valido: {chosen_axis}. Usa 'x', 'y', o 'z'")

        # Conta i blocchi in ogni area per i nomi dei file
        logging.info("Conteggio blocchi per parte 1...")
        area1_count = count_non_air_blocks_in_selection(level, dimension, area1)
        logging.info(f"Blocchi non-aria in parte 1: {area1_count}")

        logging.info("Conteggio blocchi per parte 2...")
        area2_count = count_non_air_blocks_in_selection(level, dimension, area2)
        logging.info(f"Blocchi non-aria in parte 2: {area2_count}")

        output_paths = []

        # Salva la parte 1
        part1_path = create_part_path(input_path, 1, area1_count)
        logging.info(f"Creazione parte 1: {part1_path}")
        logging.info(f"Area 1: {area1}")
        save_selection_as_schematic(level, dimension, area1, part1_path)
        output_paths.append(part1_path)

        # Salva la parte 2
        part2_path = create_part_path(input_path, 2, area2_count)
        logging.info(f"Creazione parte 2: {part2_path}")
        logging.info(f"Area 2: {area2}")
        save_selection_as_schematic(level, dimension, area2, part2_path)
        output_paths.append(part2_path)

        return output_paths

    finally:
        # Chiudi il livello originale
        level.close()

def main():
    parser = argparse.ArgumentParser(
        description="Divide un .mcstructure o .schematic in due parti se ha più di N blocchi non-aria\n"
                   "E se contiene almeno 4 chunk.\n"
                   "Per default sceglie automaticamente l'asse più lungo tra X e Z (evitando l'altezza Y).\n"
                   "I file risultanti includeranno il conteggio dei blocchi nel nome.",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "input", help="File .mcstructure o .schematic di input"
    )
    parser.add_argument(
        "--threshold", type=int, default=DEFAULT_THRESHOLD,
        help=f"Soglia blocchi non-aria per dividere (default: {DEFAULT_THRESHOLD})"
    )
    parser.add_argument(
        "--min-chunks", type=int, default=MIN_CHUNKS_FOR_SPLIT,
        help=f"Numero minimo di chunk richiesti per la divisione (default: {MIN_CHUNKS_FOR_SPLIT})"
    )
    parser.add_argument(
        "--axis", choices=["x", "y", "z"], default=None,
        help="Asse lungo cui dividere. Se non specificato, sceglie automaticamente "
             "il più lungo tra X e Z (evitando Y=altezza)"
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Output dettagliato"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Verifica che il file esista
    if not os.path.exists(args.input):
        logging.error(f"File non trovato: {args.input}")
        sys.exit(1)

    try:
        output_files = split_structure(
            args.input,
            split_axis=args.axis,
            threshold=args.threshold,
            min_chunks=args.min_chunks
        )

        if len(output_files) == 1:
            print(f"✅ Nessuna divisione necessaria: {output_files[0]}")
        else:
            print(f"✅ Divisione completata:")
            for i, path in enumerate(output_files, 1):
                print(f"   Parte {i}: {path}")

    except Exception as e:
        logging.error(f"Errore durante la divisione: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()