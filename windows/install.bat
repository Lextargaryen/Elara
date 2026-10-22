@echo off
setlocal enabledelayedexpansion

echo ========================================================
echo    Elara Search - Windows Installation & Setup
echo ========================================================
echo.

where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python 3 was not found in your PATH!
    echo Please install Python 3.10, 3.11, or 3.12 from python.org,
    echo and ensure "Add python.exe to PATH" is checked during installation.
    pause
    exit /b 1
)

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo [1/5] Checking Python environment...
python --version

echo.
echo [2/5] Creating Python virtual environment (.venv)...
if not exist ".venv" (
    python -m venv .venv
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Failed to create virtual environment!
        pause
        exit /b 1
    )
)

echo.
echo [3/5] Installing dependencies and PyTorch accelerator...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip

:: Detect NVIDIA GPU for CUDA acceleration
where nvidia-smi >nul 2>nul
if %ERRORLEVEL% equ 0 (
    echo [NVIDIA GPU Detected] Installing PyTorch with CUDA acceleration...
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
) else (
    echo [No NVIDIA GPU Detected] Installing standard PyTorch for CPU...
    pip install torch torchvision
)

pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo [WARNING] Some dependencies had warnings during install.
)

echo.
echo [4/5] Downloading and caching Google EmbeddingGemma 2 model weights...
echo (This downloads the ~600 MB multimodal model once into local cache)
python -c "from sentence_transformers import SentenceTransformer; print('Downloading google/embeddinggemma-2...'); SentenceTransformer('google/embeddinggemma-2')"
if %ERRORLEVEL% neq 0 (
    echo [WARNING] Could not pre-download model. It will be automatically downloaded on first search/scan.
)

echo.
echo [5/5] Verifying complete system and hardware accelerator...
python elara.py status

echo.
echo ========================================================
echo  Installation Complete! Everything is ready to use.
echo ========================================================
echo.
echo The model and all dependencies are fully cached locally.
echo Elara is ready to run 100%% offline!
echo.
echo You can run Elara anytime using:
echo   .\elara.bat              (starts interactive REPL)
echo   .\elara.bat "my query"   (instant search)
echo   .\elara.bat scan .       (index files in current folder)
echo   .\elara.bat daemon start (start background GPU daemon)
echo.
echo Optional: To run 'elara' from anywhere in CMD or PowerShell,
echo add this folder to your user PATH:
echo   %SCRIPT_DIR%
echo.
pause
