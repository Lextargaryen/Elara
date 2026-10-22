# Elara — Minimalistic Multimodal Semantic Search (Windows Edition)

**Elara for Windows** is a lightweight, high-performance CLI search tool for Windows 10 and 11 powered by Google DeepMind's **`EmbeddingGemma 2`** multimodal model.

Search files across your computer naturally using natural language:
- 🎬 **Videos**: `.mp4`, `.mkv`, `.mov`, `.avi`, `.webm`, `.wmv`
- 🎵 **Audio**: `.mp3`, `.wav`, `.m4a`, `.flac`, `.ogg`, `.wma`
- 🖼️ **Images**: `.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`, `.bmp`
- 📄 **Documents**: `.pdf`, `.txt`, `.md`, `.docx`
- 💻 **Code & Config**: `.py`, `.rs`, `.js`, `.ts`, `.html`, `.css`, `.json`, `.c`, `.cpp`, `.cs`, `.ps1`, `.bat`, etc.

---

## Windows-Optimized Architecture

This Windows edition is specifically engineered for the Windows operating system:
1. **Windows Local AppData Storage**: Database and state records are saved in `%LOCALAPPDATA%\elara\records.db`.
2. **TCP Loopback Background Daemon**: Instead of Unix domain sockets, the Windows daemon uses a secure local TCP loopback (`127.0.0.1:38283`) with sub-millisecond response latency (<30ms searches).
3. **Detached Process Spawning**: Daemon starts fully detached using Windows process flags (`CREATE_NO_WINDOW`), preventing any background terminal windows from popping up.
4. **Native File Opening**: The `--open` flag uses Windows `os.startfile` to open matches in your default Windows applications (Movies & TV, Media Player, Photos, Word, VS Code, etc.).
5. **Windows System & Drive Root Protection**: When scanning whole drives (`C:\`, `D:\`), Elara automatically ignores Windows system folders (`C:\Windows`, `C:\Program Files`, `C:\ProgramData`, `C:\$Recycle.Bin`, `System Volume Information`, `Recovery`) and system paging files (`pagefile.sys`, `hiberfil.sys`, `swapfile.sys`).
6. **Windows Terminal & ConHost TrueColor ANSI**: Enables native virtual terminal processing to display rich TrueColor gradients and tables across Windows Terminal, PowerShell, and CMD.
7. **Interactive Tab Completion**: Includes `pyreadline3` support for tab completion and arrow key command history.

---

## Default Behavior (Optimized for Speed)

- **Major File Types by Default**: Scans frequently searched media and documents (`mp4`, `mp3`, `wav`, `m4a`, `jpg`, `png`, `webp`, `gif`, `pdf`, `txt`, `md`, `docx`).
- **Default Size Bounds & Dynamic Video Keyframes**: Files between **50 KB and 100 MB** (up to **4 GB** specifically for video files).
  - Skips tiny files (< 50 KB): 0-byte placeholders, lockfiles, small config files.
  - Standard files (audio, images, documents, code): indexed up to 100 MB.
  - Videos: indexed up to 4 GB with **dynamic keyframing**:
    - **The bigger and longer the video, the more keyframes are sampled** (scaling from 6 keyframes for short clips up to 60 keyframes for multi-gigabyte / multi-hour videos) to comprehensively capture scene transitions and reduce representation error.
    - **Dynamic keyframe resolution**: Scaled from 384px to 512px for high-definition / multi-gigabyte videos.
    - **Strict memory bounds**: Frames are seeked via OpenCV and embedded in mini-batches of 8, keeping RAM usage < 35 MB and VRAM bounded even for 4 GB video files.
- **Fast Database Queries**: Once indexed, searches complete in **~20–30 milliseconds** against the pre-computed database.

---

## Installation & Setup

### Requirements
- **OS**: Windows 10 (64-bit) or Windows 11
- **Python**: Python 3.10, 3.11, or 3.12 (from [python.org](https://www.python.org/downloads/) or Microsoft Store). Make sure to check **"Add Python to PATH"**.
- **Hardware**: NVIDIA GeForce / RTX GPU recommended with CUDA, or modern multi-core CPU.

### Option 1: Automatic Setup (One-Click)

Run the included installer:
- In **Command Prompt (CMD)**:
  ```cmd
  install.bat
  ```
- Or in **PowerShell**:
  ```powershell
  .\install.ps1
  ```

### Option 2: Manual Setup

1. Open PowerShell or Command Prompt in the `windows` folder.
2. Create and activate a virtual environment:
   ```cmd
   python -m venv .venv
   .venv\Scripts\activate
   ```
3. Install dependencies:
   ```cmd
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```
4. Optional: Install Elara as a system-wide command:
   ```cmd
   pip install -e .
   ```

---

## Usage Guide

### 1. Interactive Terminal Mode (`elara`)
Run `elara` (or `.\elara.bat` / `.\elara.ps1`) with no arguments to enter the interactive shell:
```cmd
elara
```
Inside the interactive environment, type your search queries directly:
```text
elara > golden sunset over ocean
elara > radar animation -t video
elara > scan C:\Users\YourUser\Downloads
elara > records
elara > status
elara > exit
```

---

### 2. Direct Search (`elara "query"`)

```cmd
# Semantic search
elara "pop music song"

# Filter by type
elara "beach vacation" -t image
elara "tutorial" -t video

# Filter by file extension
elara "recording" -e mp3,wav

# Open top match directly in Windows default app
elara "quarterly revenue sheet" -o

# Filter by size
elara "high res image" --min-size 2MB
```

---

### 3. Scanning & Indexing (`elara scan`)

```cmd
# Scan current directory
elara scan .

# Scan specific folder
elara scan "C:\Users\YourUser\Documents"

# Scan entire drive (skips C:\Windows and system files safely)
elara scan C:\

# Include code, JSON, logs, and all file types
elara scan "C:\Projects" --all-types

# Scan specific extensions only
elara scan "C:\Users\YourUser\Videos" -e mp4,mkv
```

---

### 4. Background Search Daemon (`elara daemon`)

To enable instant (<30ms) searches without reloading the model on every query:

```cmd
# Start background GPU search daemon
elara daemon start

# Check status
elara daemon status

# Stop daemon
elara daemon stop
```

---

### 5. Status & Records Management

```cmd
# View system status, database size, and GPU accelerator info
elara status

# View stored records in database
elara records
elara records "C:\Users\YourUser\Pictures"

# Clear index
elara clean
```

---

## Command Reference

| Command | Description | Example |
|---|---|---|
| `elara <query>` | Instant semantic search across database | `elara "sunset over beach"` |
| `elara scan [path]` | Scan directory (default: major types, 50KB-100MB, up to 4GB videos) | `elara scan C:\Media` |
| `elara records` | List stored records in SQLite | `elara records` |
| `elara status` | Show database stats and daemon status | `elara status` |
| `elara daemon start` | Start background GPU daemon | `elara daemon start` |
| `elara -i` | Continuous interactive search prompt | `elara -i` |

### Key Flags

| Flag | Description | Default |
|---|---|---|
| `-t, --type <modality>` | Filter by modality (`video`, `audio`, `image`, `doc`, `code`) | All |
| `-e, --ext <exts>` | Comma-separated extension filter (`mp4,mp3,jpg`) | Major |
| `-a, --all-types` | Scan/include all supported file types | `False` |
| `--min-size <size>` | Minimum file size threshold | `50KB` |
| `--max-size <size>` | Maximum file size threshold (standard files) | `100MB` |
| `--max-video-size <size>` | Maximum file size threshold for video files | `4GB` |
| `--no-size-limit` | Disable min and max size checks | `False` |
| `--scan` | Scan target folder before searching | `False` |
| `-p, --path <dir>` | Restrict search to specific folder prefix | All |
| `-k, --top-k <num>` | Number of results | `5` |
| `-o, --open` | Open top match with default Windows application | `False` |
| `-q, --quiet` | Print raw file paths only (for piping) | `False` |
| `--json` | Output JSON | `False` |
| `--force` | Force re-embedding of files | `False` |
| `--prune` | Remove database records for deleted files | `False` |
