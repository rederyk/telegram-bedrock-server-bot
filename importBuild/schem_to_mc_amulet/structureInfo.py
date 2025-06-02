import nbtlib
import sys

def analyze_mcstructure(filepath):
    """
    Analizza un file .mcstructure per estrarre e stampare la sua dimensione
    e l'origine del mondo.

    Args:
        filepath (str): Il percorso del file .mcstructure.

    Returns:
        tuple: Una tupla contenente (size, origin) o (None, None) se si verifica un errore.
    """
    try:
        nbt_file = nbtlib.load(filepath, byteorder='little')

        # Accede al compound tag principale, che potrebbe non avere nome
        # o essere sotto una chiave vuota in alcune strutture NBT.
        # nbtlib.load di solito restituisce direttamente il compound tag radice.
        data_root = nbt_file
        if "" in nbt_file: # Gestisce il caso in cui i dati principali siano sotto una chiave vuota
            data_root = nbt_file[""]
            
        # Verifica la presenza dei tag necessari
        if 'size' not in data_root:
            print(f"Errore: Tag 'size' non trovato nel file {filepath}.")
            # print(f"Tag disponibili: {list(data_root.keys())}")
            return None, None
        
        if 'structure_world_origin' not in data_root:
            print(f"Errore: Tag 'structure_world_origin' non trovato nel file {filepath}.")
            # print(f"Tag disponibili: {list(data_root.keys())}")
            return None, None

        size = list(map(int, data_root['size']))
        origin = list(map(int, data_root['structure_world_origin']))

        print(f"File: {filepath}")
        print(f"  Dimensione (X, Y, Z): {size[0]}, {size[1]}, {size[2]}")
        print(f"  Origine del Mondo (X, Y, Z): {origin[0]}, {origin[1]}, {origin[2]}")
        
        return size, origin

    except FileNotFoundError:
        print(f"Errore: File non trovato a {filepath}")
        return None, None
    except Exception as e:
        print(f"Si è verificato un errore durante l'elaborazione di {filepath}: {e}")
        return None, None

if __name__ == "__main__":
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
        analyze_mcstructure(filepath)
    else:
        print("Uso: python nome_script.py <percorso_file_mcstructure>")
        # Esempio di utilizzo se vuoi testare un file specifico:
        # analyze_mcstructure("percorso/del/tuo/file.mcstructure")