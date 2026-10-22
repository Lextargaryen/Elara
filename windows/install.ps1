# Elara Search - Windows PowerShell Installer
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "   Elara Search - Windows Installation (PowerShell)" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Host "[ERROR] Python 3 was not found in your PATH!" -ForegroundColor Red
    Write-Host "Please install Python 3.10+ from python.org and check 'Add to PATH'." -ForegroundColor Yellow
    exit 1
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "[1/5] Checking Python version..." -ForegroundColor Green
python --version

Write-Host "`n[2/5] Setting up virtual environment (.venv)..." -ForegroundColor Green
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

Write-Host "`n[3/5] Installing Python dependencies and PyTorch accelerator..." -ForegroundColor Green
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip

$nvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($nvidiaSmi) {
    Write-Host "[NVIDIA GPU Detected] Installing PyTorch with CUDA acceleration..." -ForegroundColor Green
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
} else {
    Write-Host "[No NVIDIA GPU Detected] Installing standard PyTorch for CPU..." -ForegroundColor Yellow
    pip install torch torchvision
}

pip install -r requirements.txt

Write-Host "`n[4/5] Downloading and caching Google EmbeddingGemma 2 model weights..." -ForegroundColor Green
Write-Host "(This downloads the ~600 MB multimodal model once into local cache)" -ForegroundColor Cyan
python -c "from sentence_transformers import SentenceTransformer; print('Downloading google/embeddinggemma-2...'); SentenceTransformer('google/embeddinggemma-2')"

Write-Host "`n[5/5] Verifying complete system and hardware accelerator..." -ForegroundColor Green
python elara.py status

Write-Host "`n========================================================" -ForegroundColor Cyan
Write-Host " Installation Complete! Everything is ready to use." -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "The model and all dependencies are fully cached locally."
Write-Host "Elara is ready to run 100% offline!"
Write-Host ""
Write-Host "Usage in PowerShell:"
Write-Host "  .\elara.ps1              (starts interactive mode)"
Write-Host "  .\elara.ps1 ""query""      (searches files)"
Write-Host "  .\elara.ps1 scan .       (indexes current directory)"
Write-Host "  .\elara.ps1 daemon start (starts background GPU daemon)"
Write-Host ""
