#!/usr/bin/env python3
"""Executable entrypoint for Gemma 2 Multimodal Search."""

import os
import sys

# Resolve real path in case of symlinks
real_file = os.path.realpath(__file__)
script_dir = os.path.dirname(real_file)
venv_python = os.path.join(script_dir, ".venv", "bin", "python3")

if sys.executable != venv_python and os.path.exists(venv_python):
    os.execv(venv_python, [venv_python] + sys.argv)

if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

from gemma_search.cli import main

if __name__ == "__main__":
    main()
