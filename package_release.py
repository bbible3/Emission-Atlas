# Run from the command line with:
#   python build.py --as-zip --target-blender=x.y.z --version=x.y.z
#
# This script will:
# - Create a zip file with the specified Blender version and addon version.
# - If --target-blender is not specified, it reads emission_atlas.py and extracts bl_info['blender'].
# - If --version is not specified, it extracts bl_info['version'] and increments it by 0.0.1.
# - If --as-zip is not specified, it creates a folder instead of a zip archive.

import os
import re
import shutil
import sys
import zipfile
import ast

SCRIPT_FILE = "emission_atlas.py"
OUTPUT_FOLDER = "emission_atlas"

# -----------------------------
# Extract version info from bl_info
# -----------------------------
def get_blender_version(file_path):
    """Extracts the 'blender' version from bl_info in the addon script."""
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
        match = re.search(r"bl_info\s*=\s*{([^}]*)}", content, re.DOTALL)
        if match:
            try:
                bl_info_dict = ast.literal_eval(f"{{{match.group(1)}}}")
                return ".".join(map(str, bl_info_dict.get("blender", (0, 0, 0))))
            except (SyntaxError, ValueError):
                return None
    return None

def get_version(file_path):
    """Extracts the 'version' from bl_info in the addon script."""
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
        match = re.search(r"bl_info\s*=\s*{([^}]*)}", content, re.DOTALL)
        if match:
            try:
                bl_info_dict = ast.literal_eval(f"{{{match.group(1)}}}")
                return ".".join(map(str, bl_info_dict.get("version", (0, 0, 0))))
            except (SyntaxError, ValueError):
                return None
    return None

def increment_version(version):
    """Increments the last part of a semantic version string (x.y.z → x.y.z+1)."""
    if version is None:
        return "0.0.1"  # Default to first version if parsing fails
    parts = version.split('.')
    parts[-1] = str(int(parts[-1]) + 1)
    return '.'.join(parts)

# -----------------------------
# Main build function
# -----------------------------
def main():
    as_zip = False
    target_blender = None
    version = None

    # Parse command-line arguments
    for arg in sys.argv[1:]:
        if arg == '--as-zip':
            as_zip = True
        elif arg.startswith('--target-blender='):
            target_blender = arg.split('=')[1]
        elif arg.startswith('--version='):
            version = arg.split('=')[1]

    # Extract bl_info if not provided via command-line arguments
    if target_blender is None:
        target_blender = get_blender_version(SCRIPT_FILE)
        if target_blender is None:
            print("Error: Could not determine target Blender version from emission_atlas.py")
            return

    if version is None:
        version = get_version(SCRIPT_FILE)
        version = increment_version(version)

    # Output names
    zip_file_name = f"emission_atlas_{version}_blender_{target_blender}.zip"

    # Remove existing build folder if it exists
    if os.path.exists(OUTPUT_FOLDER):
        shutil.rmtree(OUTPUT_FOLDER)
    
    os.mkdir(OUTPUT_FOLDER)

    # Copy necessary files
    shutil.copy(SCRIPT_FILE, OUTPUT_FOLDER)
    if os.path.exists("LICENSE"):
        shutil.copy("LICENSE", OUTPUT_FOLDER)
    if os.path.exists("README.md"):
        shutil.copy("README.md", OUTPUT_FOLDER)

    # If `--as-zip` was provided, package everything into a zip file
    if as_zip:
        with zipfile.ZipFile(zip_file_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(OUTPUT_FOLDER):
                for file in files:
                    zipf.write(os.path.join(root, file), os.path.relpath(os.path.join(root, file), OUTPUT_FOLDER))

        # Clean up the folder after zipping
        shutil.rmtree(OUTPUT_FOLDER)

        print(f"✅ Build complete: {zip_file_name}")
    else:
        print(f"✅ Build complete: Folder '{OUTPUT_FOLDER}' created")

# -----------------------------
# Entry point
# -----------------------------
if __name__ == '__main__':
    main()
