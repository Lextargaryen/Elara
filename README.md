# Elara — Minimalistic Multimodal Semantic Search (Linux & Windows)

**Elara** is a lightweight, blazing-fast CLI search tool powered by Google DeepMind's **`EmbeddingGemma 2`** multimodal model.

Search files across your computer naturally using natural language:
- 🎬 **Videos**: `.mp4`, `.mkv`, `.mov`, `.avi`, `.webm`, `.wmv` (with dynamic keyframing up to 4 GB)
- 🎵 **Audio**: `.mp3`, `.wav`, `.m4a`, `.flac`, `.ogg`, `.wma`
- 🖼️ **Images**: `.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`, `.bmp`
- 📄 **Documents**: `.pdf`, `.txt`, `.md`, `.docx`
- 💻 **Code & Config**: `.py`, `.rs`, `.js`, `.ts`, `.html`, `.css`, `.json`, `.c`, `.cpp`, `.cs`, `.sh`, `.ps1`, `.bat`, etc.

---

## ⚡ Quick Start by Operating System

### 🐧 Linux
```bash
git clone https://github.com/Lextargaryen/Elara.git
cd Elara
chmod +x install.sh
./install.sh
```

### 🪟 Windows
Run the one-click Windows installer:
- In **Command Prompt (CMD)**:
  ```cmd
  cd windows
  install.bat
  ```
- Or in **PowerShell**:
  ```powershell
  cd windows
  .\install.ps1
  ```
See the dedicated [**Windows Documentation**](windows/README.md) for Windows-specific options.

---

## Default Behavior (Optimized for Speed)

To make scanning fast and avoid indexing system noise:
1. **Major File Types by Default**: Scans frequently searched media and documents (`mp4`, `mp3`, `wav`, `m4a`, `jpg`, `png`, `webp`, `gif`, `pdf`, `txt`, `md`, `docx`).
2. **Default Size Bounds & Dynamic Video Keyframes**: Scans files between **50 KB and 100 MB** (up to **4 GB** specifically for videos).
   - Skips tiny files (< 50 KB): 0-byte placeholders, lockfiles, small config files.
   - Standard files (audio, image, documents, code): indexed up to 100 MB.
   - Videos (`.mp4`, `.mkv`, `.mov`, `.avi`, `.webm`): indexed up to 4 GB with **dynamic keyframing**:
     - **The bigger and longer the video, the more keyframes are sampled** (scaling from 6 keyframes for short clips up to 60 keyframes for multi-gigabyte / multi-hour videos) to comprehensively capture scene transitions and reduce representation error.
     - **Dynamic keyframe resolution**: Scaled from 384px to 512px for high-definition / multi-gigabyte videos.
     - **Strict memory bounds**: Frames are seeked via OpenCV and embedded in mini-batches of 8, keeping RAM usage < 35 MB and VRAM bounded even for 4 GB video files.
3. **Database-Only Fast Search**: By default, `elara "query"` queries the pre-computed SQLite database (`~/.local/share/elara/records.db`) via the background GPU daemon in **~20–30 milliseconds**.

All of these defaults can be overridden whenever needed.

---

## Usage Guide

### 1. Interactive Environment (`elara`)
Simply run `elara` without arguments to launch the interactive terminal environment with the ASCII banner:
```bash
elara
```
Once inside, you never need to type `elara` again:
```text
elara ❯ pop music song
elara ❯ radar scan -t video
elara ❯ scan ~/Downloads
elara ❯ records
elara ❯ status
elara ❯ help
elara ❯ exit
```

---

### 2. CLI Direct Search (`elara search` or `elara "query"`)
You can also run one-off searches directly from your terminal:
```bash
# Search for songs or audio
elara "pop music song espresso"


# Search for pictures
elara "golden sunset over the ocean water"

# Search for recipes or notes
elara "recipe for baking a sweet chocolate cake"
```

#### Search Overrides: Filter by Type or Extension
You can narrow down results to specific file types during search:
```bash
# Search only audio files
elara "espresso" -t audio

# Search only MP3s or WAVs
elara "espresso" -e mp3
elara "melody" -e wav,flac

# Search only videos or images
elara "animated radar circle" -t video
elara "forest landscape" -t image
```

#### Search Overrides: Filter by Size
```bash
# Only files larger than 1 MB
elara "espresso" --min-size 1MB

# Only small files under 500 KB
elara "recipe" --max-size 500KB
```

#### Search Overrides: Scan Before Searching (`--scan`)
If you want Elara to scan a folder before searching:
```bash
elara "my document" --scan -p ~/Documents
```

#### Pipe to Other Linux Tools (`-q`)
```bash
# Pipe directly to mpv player
elara -q "espresso" -e mp3 | xargs -d '\n' mpv

# Fuzzy find with fzf
elara -q "sunset" | fzf
```

---

### 2. Scanning & Indexing (`elara scan`)

#### Default Scan (Major Types, 50 KB – 100 MB, up to 4 GB for videos)
```bash
# Scan a directory
elara scan ~/Downloads

# Scan current folder
elara scan .
```

#### Overriding File Types
```bash
# Scan literally everything supported (includes code, json, logs, csv, etc.)
elara scan ~/Projects --all-types

# Scan only videos and audio
elara scan ~/Media -t video
elara scan ~/Music -t audio

# Scan specific extensions only
elara scan ~/Downloads -e mp4,mkv,mp3
```

#### Overriding Size Limits
```bash
# Custom range: 10 KB to 500 MB
elara scan ~/Videos --min-size 10KB --max-size 500MB

# No size limits (includes files < 50KB and > 100MB)
elara scan ~/Documents --no-size-limit
```

#### Scanning Whole Disk (`/` or `~`)
Elara automatically ignores system directories (`/proc`, `/sys`, `/dev`, `/run`, `/tmp`, `/boot`) and caches (`node_modules`, `.git`, `.venv`, `Trash`):
```bash
elara scan ~
elara scan /
```

---

### 3. Managing the Instant Search Daemon

```bash
elara daemon status    # Check daemon health & PID
elara daemon start     # Start background GPU daemon (<30ms searches)
elara daemon stop      # Stop background daemon
```

---

### 4. Viewing Kept Records & Status

```bash
elara records          # View persistent database records
elara records testimg  # Filter records by directory
elara status           # View database size, defaults, and GPU accelerator
elara clean            # Reset/clear database records
```

---

## Command Reference

| Command | Description | Example |
|---|---|---|
| `elara <query>` | Instant semantic search across database | `elara "sunset over ocean"` |
| `elara scan [path]` | Scan directory (default: major types, 50KB-100MB, up to 4GB videos) | `elara scan ~/Music` |
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
| `-o, --open` | Open top match with default application | `False` |
| `-q, --quiet` | Print raw file paths only (for pipes) | `False` |
| `--json` | Output JSON | `False` |
| `--force` | Force re-embedding of files | `False` |
| `--prune` | Remove database records for deleted files | `False` |
