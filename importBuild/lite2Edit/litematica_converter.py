import subprocess
import os
import logging

logger = logging.getLogger(__name__)

def convert_litematica_to_schematic(input_file, output_dir):
    """
    Converts a .litematica file to .schematic using the Lite2Edit JAR.
    Args:
        input_file: Path to the .litematica file.
        output_dir: Directory to save the converted .schematic file.
    Returns:
        Path to the converted .schematic file, or None if the conversion failed.
    """
    try:
        jar_path = os.path.join(os.path.dirname(__file__), "Lite2Edit.jar")
        command = ["java", "-jar", jar_path, "--convert", input_file]
        process = subprocess.run(command, cwd=output_dir, capture_output=True, text=True)

        if process.returncode == 0:
            # Parse the output to get the output file name
            output = process.stdout
            for line in output.splitlines():
                if "Exported to" in line:
                    output_file = os.path.join(output_dir, line.split("Exported to ")[1].strip())
                    return output_file
            logger.error(f"Could not find output file in Lite2Edit output: {output}")
            return None
        else:
            logger.error(f"Lite2Edit conversion failed: {process.stderr}")
            return None
    except Exception as e:
        logger.exception("Error during litematica to schematic conversion:")
        return None
