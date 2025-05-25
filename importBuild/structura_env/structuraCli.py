import argparse
import os
import sys
from pathlib import Path

def find_structura_path():
    """Trova il percorso della cartella Structura."""
    # Cerca prima nella directory corrente
    current_dir = Path.cwd()
    
    # Cerca Structura nella directory corrente
    if (current_dir / "structura_core.py").exists():
        return current_dir
    
    # Cerca nelle sottocartelle
    for item in current_dir.iterdir():
        if item.is_dir():
            # Cerca cartelle che contengono "structura" nel nome (case insensitive)
            if "structura" in item.name.lower():
                if (item / "structura_core.py").exists():
                    return item
    
    # Cerca in tutte le sottocartelle per structura_core.py
    for item in current_dir.iterdir():
        if item.is_dir():
            if (item / "structura_core.py").exists():
                return item
    
    return None

def setup_structura_environment():
    """Configura l'ambiente per utilizzare Structura."""
    structura_path = find_structura_path()
    
    if structura_path is None:
        print("Errore: Impossibile trovare la cartella Structura.")
        print("Assicurati che:")
        print("1. La cartella Structura sia nella directory corrente, oppure")
        print("2. Una sottocartella contenga 'structura_core.py'")
        return False
    
    print(f"Trovata cartella Structura in: {structura_path}")
    
    # Aggiungi il percorso di Structura al PYTHONPATH
    if str(structura_path) not in sys.path:
        sys.path.insert(0, str(structura_path))
    
    # Cambia la directory di lavoro per i percorsi relativi
    original_cwd = os.getcwd()
    os.chdir(structura_path)
    
    return True

def main():
    parser = argparse.ArgumentParser(description="Crea un pacchetto di risorse Structura da file .mcstructure.")

    parser.add_argument("pack_name",
                        help="Il nome del pacchetto di output (verrà creata una cartella con questo nome).")
    parser.add_argument("-s", "--structures", nargs='+', required=True,
                        help="Percorso/i del/i file .mcstructure da includere. Minimo uno.")
    parser.add_argument("-n", "--nametags", nargs='*',
                        help="Nomi (nametag) per ogni struttura, nell'ordine dei file .mcstructure forniti. Se omesso per più strutture (non in modalità 'big_build'), i nametag verranno generati dai nomi dei file.")
    parser.add_argument("-o", "--offsets", nargs='*',
                        help="Offset per ogni struttura nel formato 'x,y,z'. Fornire un set di coordinate per ogni struttura, nell'ordine dei file .mcstructure. Esempio: 0,0,0 -10,5,0")
    parser.add_argument("-p", "--opacity", type=int, default=60,
                        help="Opacità dei blocchi fantasma (0-100, default: 40). Valori più bassi sono più trasparenti (0=trasparente, 100=opaco).")
    parser.add_argument("-i", "--icon", default="lookups/pack_icon.png",
                        help="Percorso del file icona del pacchetto (PNG). Default: lookups/pack_icon.png")
    parser.add_argument("-l", "--list", action='store_true',
                        help="Genera un file di testo con la lista dei blocchi.")
    parser.add_argument("-b", "--big_build", action='store_true',
                        help="Abilita la modalità 'big build' per combinare tutte le strutture in un unico modello grande. Gli offset globali per questa modalità vengono forniti tramite --big_offset.")
    parser.add_argument("--big_offset", default="0,0,0",
                        help="Offset globale per la modalità 'big_build' nel formato 'x,y,z'. Usato solo se --big_build è specificato. Default: 0,0,0")
    parser.add_argument("--structura_path", 
                        help="Percorso esplicito alla cartella Structura (opzionale, se non specificato verrà cercata automaticamente)")

    args = parser.parse_args()

    # Salva la directory originale (dove lanciamo lo script)
    original_cwd = Path.cwd()

    # Setup dell'ambiente Structura
    if args.structura_path:
        structura_path = Path(args.structura_path)
        if not (structura_path / "structura_core.py").exists():
            print(f"Errore: Percorso Structura specificato non valido: {structura_path}")
            return
        sys.path.insert(0, str(structura_path))
        os.chdir(structura_path)
    else:
        if not setup_structura_environment():
            return

    # Ora possiamo importare structura_core
    try:
        import structura_core
    except ImportError as e:
        print(f"Errore: Impossibile importare 'structura_core': {e}")
        print("Assicurati che 'structura_core.py' sia accessibile.")
        return

    # Converti i percorsi delle strutture in percorsi assoluti
    # (perché abbiamo cambiato directory di lavoro)
    original_structures = args.structures
    resolved_structures = []
    
    for struct_path in original_structures:
        struct_path_obj = Path(struct_path)
        if struct_path_obj.is_absolute():
            resolved_structures.append(str(struct_path_obj))
        else:
            # Cerca il file rispetto alla directory originale
            original_path = original_cwd / struct_path_obj
            if original_path.exists():
                resolved_structures.append(str(original_path))
            else:
                # Prova rispetto alla directory corrente (Structura)
                current_path = Path.cwd() / struct_path_obj
                if current_path.exists():
                    resolved_structures.append(str(current_path))
                else:
                    print(f"Errore: File struttura non trovato: {struct_path}")
                    return
    
    args.structures = resolved_structures

    # Controlla se il pacchetto esiste nella directory originale
    pack_path_original = original_cwd / args.pack_name
    mcpack_path_original = original_cwd / f"{args.pack_name}.mcpack"
    if pack_path_original.exists() or mcpack_path_original.exists():
        print(f"Errore: La cartella o il file del pacchetto '{args.pack_name}' esistono già nella directory di lancio. Scegli un nome diverso o rimuovi quelli esistenti.")
        return

    num_structures = len(args.structures)
    nametags_for_processing = []

    if args.big_build:
        pass
    elif num_structures == 1:
        if args.nametags:
            if len(args.nametags) == 1:
                nametags_for_processing = args.nametags
            else:
                print(f"Attenzione: Forniti {len(args.nametags)} nametag per una singola struttura. Verrà usato il primo: '{args.nametags[0]}'.")
                nametags_for_processing = [args.nametags[0]]
        else:
            nametags_for_processing = [""]
    else:
        if args.nametags:
            if len(args.nametags) == num_structures:
                nametags_for_processing = args.nametags
            else:
                print(f"Errore: Il numero di nametag forniti ({len(args.nametags)}) non corrisponde al numero di strutture ({num_structures}).")
                print("È necessario fornire un nametag per ogni file struttura oppure omettere del tutto l'argomento --nametags per la generazione automatica.")
                return
        else:
            print("Info: Argomento --nametags non fornito per più strutture. I nametag verranno generati automaticamente dai nomi dei file.")
            for struct_file in args.structures:
                base_name = os.path.basename(struct_file)
                nametag = os.path.splitext(base_name)[0]
                nametags_for_processing.append(nametag)
            print(f"Nametag generati: {nametags_for_processing}")

    parsed_offsets = []
    if args.offsets:
        if len(args.offsets) != num_structures and not args.big_build:
            print(f"Attenzione: Il numero di offset ({len(args.offsets)}) non corrisponde al numero di strutture ({num_structures}). Verranno usati gli offset forniti per le prime strutture, gli altri avranno [0,0,0].")
        for offset_str in args.offsets:
            try:
                offset_coords = list(map(int, offset_str.split(',')))
                if len(offset_coords) != 3:
                    raise ValueError("L'offset deve contenere 3 coordinate.")
                parsed_offsets.append(offset_coords)
            except ValueError as e:
                print(f"Errore: Formato offset non valido '{offset_str}'. Usare x,y,z. Dettaglio: {e}")
                return
    else:
        parsed_offsets = [[0,0,0]] * num_structures

    parsed_big_offset = [0,0,0]
    if args.big_build:
        try:
            parsed_big_offset = list(map(int, args.big_offset.split(',')))
            if len(parsed_big_offset) != 3:
                raise ValueError
        except ValueError:
            print(f"Errore: Formato offset non valido per --big_offset '{args.big_offset}'. Usare x,y,z.")
            return

    # Crea il pack nella directory di Structura (per accesso a lookups) 
    # ma con il nome che poi sposteremo
    structura_pack = structura_core.structura(args.pack_name)

    alpha_value_for_core = args.opacity / 100.0
    structura_pack.set_opacity(alpha_value_for_core)

    if os.path.exists(args.icon):
        structura_pack.set_icon(args.icon)
    else:
        print(f"Attenzione: File icona '{args.icon}' non trovato. Verrà usata l'icona di default se disponibile nel percorso di structura_core.")

    if args.big_build:
        print("Modalità Big Build attivata.")
        if num_structures == 0:
            print("Errore: Nessun file struttura fornito per la modalità big_build.")
            return
        for i in range(num_structures):
            file_basename = os.path.basename(args.structures[i])
            structura_pack.add_model(file_basename, args.structures[i])
        structura_pack.make_big_model(parsed_big_offset)
        if args.list:
            structura_pack.make_big_blocklist()
    else:
        if num_structures == 1:
            nametag_to_use = nametags_for_processing[0]
            offset_to_use = parsed_offsets[0]

            structura_pack.add_model(nametag_to_use, args.structures[0])
            structura_pack.set_model_offset(nametag_to_use, offset_to_use)
        else:
            for i in range(num_structures):
                nametag_to_use = nametags_for_processing[i]
                offset_to_use = parsed_offsets[i] if i < len(parsed_offsets) else [0,0,0]
                structura_pack.add_model(nametag_to_use, args.structures[i])
                structura_pack.set_model_offset(nametag_to_use, offset_to_use)

        structura_pack.generate_with_nametags()
        if args.list:
            structura_pack.make_nametag_block_lists()

        if any(tag and tag.strip() != "" for tag in nametags_for_processing):
            structura_pack.generate_nametag_file()

    print("Compilazione del pacchetto in corso...")
    created_file = structura_pack.compile_pack()
    
    # Sposta il file creato nella directory originale
    created_path = Path(created_file)
    if created_path.exists():
        destination = original_cwd / created_path.name
        import shutil
        shutil.move(str(created_path), str(destination))
        print(f"Pacchetto creato con successo: {destination}")
        
        # Sposta anche la cartella temporanea se esiste
        temp_folder = Path(args.pack_name)
        if temp_folder.exists():
            destination_folder = original_cwd / temp_folder.name
            if destination_folder.exists():
                shutil.rmtree(str(destination_folder))
            shutil.move(str(temp_folder), str(destination_folder))
    else:
        print(f"Pacchetto creato: {created_file}")

    skipped = structura_pack.get_skipped()
    if skipped:
        print("\nBlocchi non supportati e saltati:")
        for block_name, variants in skipped.items():
            for variant, count in variants.items():
                print(f"- {block_name} (Variante: {variant}): {count} volte")
        print(f"Un file '{args.pack_name}_skipped.txt' potrebbe essere stato creato con questi dettagli.")

if __name__ == "__main__":
    main()