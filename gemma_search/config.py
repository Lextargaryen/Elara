"""Configuration, system constants, and filtering defaults for Elara Search."""

import os
from pathlib import Path
from typing import Union, Set

APP_NAME = "elara"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_DB_PATH = DATA_DIR / "records.db"
SOCKET_PATH = str(DATA_DIR / "daemon.sock")
PID_PATH = str(DATA_DIR / "daemon.pid")
LOCK_PATH = str(DATA_DIR / "daemon.lock")


# Default size thresholds: 50 KB to 100 MB, up to 4 GB for videos
DEFAULT_MIN_FILE_SIZE_BYTES = 50 * 1024                     # 50 KB
DEFAULT_MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024             # 100 MB
DEFAULT_MAX_VIDEO_SIZE_BYTES = 4 * 1024 * 1024 * 1024       # 4 GB
MAX_TEXT_CHARS = 12000

# Dynamic video keyframe sampling bounds
MIN_VIDEO_KEYFRAMES = 6
MAX_VIDEO_KEYFRAMES = 60
DEFAULT_VIDEO_FRAME_BATCH_SIZE = 8


# Major extensions that people frequently search for (default scan filter)
MAJOR_VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm"}
MAJOR_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}
MAJOR_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAJOR_DOC_EXTS   = {".pdf", ".txt", ".md", ".docx"}

MAJOR_EXTENSIONS: Set[str] = (
    MAJOR_VIDEO_EXTS | MAJOR_AUDIO_EXTS | MAJOR_IMAGE_EXTS | MAJOR_DOC_EXTS
)

# Extended file types for code, data, and config
CODE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".rs", ".go",
    ".c", ".cpp", ".h", ".hpp", ".java", ".sh", ".bash", ".zsh",
    ".json", ".yaml", ".yml", ".toml", ".sql", ".php", ".rb", ".swift",
    ".kt", ".lua", ".r", ".cs", ".scala", ".dart"
}
ADDITIONAL_DOC_EXTS = {".csv", ".tsv", ".log", ".xml", ".ini", ".cfg", ".conf", ".env", ".tex", ".rst"}
ADDITIONAL_IMAGE_EXTS = {".bmp", ".tiff", ".tif"}
ADDITIONAL_VIDEO_EXTS = {".flv", ".wmv"}
ADDITIONAL_AUDIO_EXTS = {".aac"}

ALL_SUPPORTED_EXTENSIONS: Set[str] = (
    MAJOR_EXTENSIONS | CODE_EXTS | ADDITIONAL_DOC_EXTS |
    ADDITIONAL_IMAGE_EXTS | ADDITIONAL_VIDEO_EXTS | ADDITIONAL_AUDIO_EXTS
)

# Directories to skip when scanning disk or home directory
IGNORED_DIR_NAMES = {
    "proc", "sys", "dev", "run", "tmp", "var", "boot", "lost+found",
    ".git", ".svn", ".hg", ".venv", "venv", "env", "__pycache__",
    "node_modules", ".cache", ".npm", ".yarn", ".cargo", ".rustup",
    ".gradle", ".m2", "target", "build", "dist", ".tox",
    "Trash", ".local/share/Trash", ".var", ".flatpak", ".snap",
    ".docker", ".singularity", ".wine", ".steam", ".steam-lutris",
    ".system_generated", ".idea", ".vscode"
}

SYSTEM_ROOT_IGNORES = {
    "/proc", "/sys", "/dev", "/run", "/tmp", "/var/tmp", "/var/run",
    "/var/lib/docker", "/var/lib/containerd", "/boot", "/lost+found",
    "/etc", "/usr", "/opt", "/snap", "/var/cache", "/var/log"
}


def parse_size_bytes(val: Union[str, int, float, None]) -> Optional[int]:
    """Parse human readable size string like '50KB', '100MB', '1.5GB' into bytes."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val).strip().upper()
    if not s:
        return None
    try:
        if s.endswith("KB") or s.endswith("K"):
            return int(float(s.rstrip("KKB")) * 1024)
        if s.endswith("MB") or s.endswith("M"):
            return int(float(s.rstrip("MMB")) * 1024 * 1024)
        if s.endswith("GB") or s.endswith("G"):
            return int(float(s.rstrip("GGB")) * 1024 * 1024 * 1024)
        if s.endswith("B"):
            return int(float(s[:-1]))
        return int(float(s))
    except ValueError:
        return None


def format_bytes(size: int) -> str:
    """Format bytes into readable string."""
    fsize = float(size)
    for unit in ["B", "KB", "MB", "GB"]:
        if fsize < 1024.0:
            return f"{fsize:.1f} {unit}" if unit != "B" else f"{int(fsize)} B"
        fsize /= 1024.0
    return f"{fsize:.1f} TB"
