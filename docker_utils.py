# minecraft_telegram_bot/docker_utils.py
import asyncio
import subprocess
import re
from config import CONTAINER, get_logger

logger = get_logger(__name__)

async def run_docker_command(command_args: list, read_output: bool = False, timeout: int = 15):
    """Esegue asincronamente un comando Docker."""
    if not CONTAINER and "exec" in command_args: # Non bloccare 'docker logs' se CONTAINER non c'è
        logger.error("Variabile CONTAINER non impostata, impossibile eseguire il comando Docker exec.")
        # Potrebbe essere preferibile sollevare un'eccezione personalizzata qui
        raise ValueError("CONTAINER non configurato per l'esecuzione del comando Docker.")

    try:
        logger.debug(f"Esecuzione comando Docker: {' '.join(command_args)}")
        process = await asyncio.create_subprocess_exec(
            *command_args,
            stdout=asyncio.subprocess.PIPE if read_output else asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)

        decoded_stderr = stderr.decode().strip() if stderr else ""
        if decoded_stderr:
            logger.info(f"Output stderr dal comando Docker '{' '.join(command_args)}': {decoded_stderr}")

        if process.returncode != 0:
            logger.warning(
                f"Comando Docker '{' '.join(command_args)}' ha restituito {process.returncode}. stderr: {decoded_stderr}"
            )
            # Non sollevare eccezione per alcuni comandi che potrebbero comportarsi così
            # if not ("send-command" in command_args and "list" in command_args):
            raise subprocess.CalledProcessError(
                process.returncode, command_args,
                output=stdout.decode().strip() if stdout and read_output else None,
                stderr=decoded_stderr
            )

        if read_output:
            return stdout.decode().strip() if stdout else ""
        return process.returncode
    except asyncio.TimeoutError:
        logger.error(f"Timeout per il comando Docker: {' '.join(command_args)}")
        raise
    except subprocess.CalledProcessError:
        raise
    except Exception as e:
        logger.error(f"Errore imprevisto eseguendo il comando Docker {' '.join(command_args)}: {e}", exc_info=True)
        raise


async def get_online_players_from_server() -> list:
    """Ottiene la lista dei giocatori online."""
    if not CONTAINER:
        logger.error("Variabile CONTAINER non impostata, impossibile ottenere i giocatori online.")
        return []
    try:
        list_command_args = ["docker", "exec", CONTAINER, "send-command", "list"]
        logger.info(f"Esecuzione comando per aggiornare lista giocatori: {' '.join(list_command_args)}")
        try:
            await run_docker_command(list_command_args, read_output=False, timeout=5)
        except subprocess.CalledProcessError as e:
            logger.warning(
                f"Comando '{' '.join(list_command_args)}' ha restituito un errore (codice {e.returncode}), "
                f"ma si procede con la lettura dei log. Stderr: {e.stderr}"
            )
        except asyncio.TimeoutError:
            logger.error(
                f"Timeout durante l'esecuzione del comando '{' '.join(list_command_args)}'. "
                "Impossibile aggiornare la lista giocatori."
            )
            return []
        except Exception as e:
            logger.error(
                f"Errore imprevisto eseguendo '{' '.join(list_command_args)}': {e}. "
                "Si tenta comunque di leggere i log."
            )

        await asyncio.sleep(1.0) # Attendi che il comando list venga processato e loggato

        logs_command_args = ["docker", "logs", "--tail", "100", CONTAINER]
        logger.info(f"Lettura log: {' '.join(logs_command_args)}")
        output = await run_docker_command(logs_command_args, read_output=True, timeout=5)

        if not output:
            logger.warning("Nessun output dai log dopo il comando list.")
            return []

        lines = output.splitlines()
        player_list = []

        for i in reversed(range(len(lines))):
            current_line_raw = lines[i]
            current_line_content = current_line_raw

            # Rimuovi il timestamp e il livello di log, se presenti
            # Esempio: [20:42:25 INFO]: There are 0 of a max of 20 players online:
            # Esempio: [Server thread/INFO]: There are 0 of a max of 20 players online:
            # Esempio bedrock: [INFO] There are 0/20 players online:
            # Esempio bedrock con send-command: [INFO]คอนโซล: There are 0/20 players online:
            match = re.search(r"\]: (.*)|\] (.*)|คอนโซล: (.*)", current_line_content) # Aggiunto caso bedrock semplice
            if match:
                current_line_content = next(g for g in match.groups() if g is not None)

            current_line_lower = current_line_content.lower()

            if ("players online:" in current_line_lower and "there are" in current_line_lower) or \
               ("players online:" in current_line_lower): # Pattern Bedrock "0/20 players online:"

                # Tentativo di estrarre i giocatori dalla stessa riga
                if ":" in current_line_content:
                    potential_players_str = current_line_content.split(":", 1)[1].strip()
                    if potential_players_str: # Se c'è qualcosa dopo i due punti
                         # Escludi messaggi come "max players online" che non contengono la lista
                        if "max players online" not in current_line_lower:
                            player_list = [
                                p.strip() for p in potential_players_str.split(',')
                                if p.strip() and "no players online" not in p.lower() and "nessun giocatore connesso" not in p.lower()
                            ]
                            if player_list:
                                logger.info(f"Giocatori online trovati (stessa riga): {player_list}")
                                return player_list

                # Se non trovati sulla stessa riga (o la lista era vuota ma c'era il trigger),
                # controlla la riga successiva (comune per alcuni server Java)
                if i + 1 < len(lines):
                    next_line_raw = lines[i+1]
                    next_line_content = next_line_raw
                    match_next = re.search(r"\]: (.*)|\] (.*)|คอนโซล: (.*)", next_line_content)
                    if match_next:
                        next_line_content = next(g for g in match_next.groups() if g is not None)

                    next_line_content_stripped = next_line_content.strip()

                    # Verifica che la riga successiva non sia un'altra riga di log strutturata
                    # e che contenga effettivamente nomi di giocatori
                    if next_line_content_stripped and \
                       not next_line_content_stripped.startswith("[") and \
                       " INFO" not in next_line_raw and \
                       " WARN" not in next_line_raw and \
                       " ERROR" not in next_line_raw and \
                       "คอนโซล:" not in next_line_raw:
                        if "no players online" not in next_line_content_stripped.lower() and \
                           "nessun giocatore connesso" not in next_line_content_stripped.lower():
                            player_list = [p.strip() for p in next_line_content_stripped.split(',') if p.strip()]
                            if player_list:
                                logger.info(f"Giocatori online trovati (riga successiva): {player_list}")
                                return player_list

                logger.info("Trovato 'players online:' ma nessun giocatore elencato o lista vuota nelle righe pertinenti.")
                return [] # Indica che 0 giocatori sono online

        logger.info("Pattern 'players online:' non trovato nei log recenti dopo il comando 'list'.")
        return []
    except asyncio.TimeoutError:
        logger.error("Timeout ottenendo i giocatori online (fase lettura log).")
    except subprocess.CalledProcessError as e:
        logger.error(f"Errore comando Docker leggendo i log per get_online_players: {e.cmd} - {e.stderr or e.output or e}")
    except ValueError as e: # Per l'errore di CONTAINER non configurato
        logger.error(f"Errore configurazione in get_online_players: {e}")
    except Exception as e:
        logger.error(f"Errore generico ottenendo giocatori online: {e}", exc_info=True)
    return []