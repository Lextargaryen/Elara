#!/usr/bin/env python3
"""Elara - Multimodal Semantic Search CLI for Windows."""

import os
import sys
from pathlib import Path

# Add project root directory to sys.path
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

# Automatically use local virtualenv Python if launched with system Python
if sys.platform == "win32":
    venv_python = root_dir / ".venv" / "Scripts" / "python.exe"
    this_script = str(Path(__file__).resolve())
    if venv_python.exists() and Path(sys.executable).resolve() != venv_python.resolve():
        import subprocess
        sys.exit(subprocess.call([str(venv_python), this_script] + sys.argv[1:]))

from gemma_search.cli import main

if __name__ == "__main__":
    main()
