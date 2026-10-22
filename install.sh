#!/usr/bin/env bash
set -e

echo "========================================================"
echo "    Elara Search - Linux Installation & Setup"
echo "========================================================"
echo

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v python3 &>/dev/null; then
    echo "[ERROR] Python 3 was not found! Please install python3 (3.10+) via your package manager."
    exit 1
fi

echo "[1/5] Checking Python environment..."
python3 --version

echo
echo "[2/5] Creating Python virtual environment (.venv)..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

echo
echo "[3/5] Installing dependencies and PyTorch accelerator..."
source .venv/bin/activate
pip install --upgrade pip

if command -v nvidia-smi &>/dev/null; then
    echo "[NVIDIA GPU Detected] Installing PyTorch with CUDA acceleration..."
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
else
    echo "[No NVIDIA GPU Detected] Installing standard PyTorch for CPU..."
    pip install torch torchvision
fi

pip install -r requirements.txt

echo
echo "[4/5] Downloading and caching Google EmbeddingGemma 2 model weights..."
echo "(This downloads the ~600 MB multimodal model once into local cache)"
python -c "from sentence_transformers import SentenceTransformer; print('Downloading google/embeddinggemma-2...'); SentenceTransformer('google/embeddinggemma-2')" || true

echo
echo "[5/5] Configuring system launcher (~/.local/bin/elara)..."
mkdir -p "$HOME/.local/bin"
chmod +x "$SCRIPT_DIR/elara"
ln -sf "$SCRIPT_DIR/elara" "$HOME/.local/bin/elara"

echo
echo "Verifying installation..."
"$SCRIPT_DIR/elara" status

echo
echo "========================================================"
echo " Installation Complete! Everything is ready to use."
echo "========================================================"
echo
echo "Run Elara anytime using:"
echo "  elara                (starts interactive REPL)"
echo "  elara \"my query\"     (instant search)"
echo "  elara scan .         (index files in current folder)"
echo "  elara daemon start   (start background GPU daemon)"
echo
