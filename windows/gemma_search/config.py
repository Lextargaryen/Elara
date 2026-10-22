"""Configuration, system constants, and filtering defaults for Elara Search (Windows)."""

import os
import sys
from pathlib import Path
from typing import Union, Set, Optional

APP_NAME = "elara"

# Windows standard application data directory (%LOCALAPPDATA%\elara)
if sys.platform == "win32":
    _local_appdata = os.environ.get("LOCALAPPDATA")
    if _local_appdata:
        DATA_DIR = Path(_local_appdata) / APP_NAME
    else:
        DATA_DIR = Path.home() / "AppData" / "Local" / APP_NAME
else:
    # Fallback if running on Unix-like environment or testing
    DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME

DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_DB_PATH = DATA_DIR / "records.db"
PID_PATH = str(DATA_DIR / "daemon.pid")
PORT_PATH = str(DATA_DIR / "daemon.port")
LOCK_PATH = str(DATA_DIR / "daemon.lock")

# Windows loopback TCP IPC for daemon
DAEMON_HOST = "127.0.0.1"
DEFAULT_DAEMON_PORT = 38283


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
    ".c", ".cpp", ".h", ".hpp", ".java", ".cs", ".sh", ".ps1", ".bat", ".cmd",
    ".json", ".yaml", ".yml", ".toml", ".sql", ".php", ".rb", ".swift",
    ".kt", ".lua", ".r", ".scala", ".dart"
}
ADDITIONAL_DOC_EXTS = {".csv", ".tsv", ".log", ".xml", ".ini", ".cfg", ".conf", ".env", ".tex", ".rst"}
ADDITIONAL_IMAGE_EXTS = {".bmp", ".tiff", ".tif", ".ico"}
ADDITIONAL_VIDEO_EXTS = {".flv", ".wmv", ".m4v"}
ADDITIONAL_AUDIO_EXTS = {".aac", ".wma"}

ALL_SUPPORTED_EXTENSIONS: Set[str] = (
    MAJOR_EXTENSIONS | CODE_EXTS | ADDITIONAL_DOC_EXTS |
    ADDITIONAL_IMAGE_EXTS | ADDITIONAL_VIDEO_EXTS | ADDITIONAL_AUDIO_EXTS
)

# Directory names to skip when traversing directories on Windows
IGNORED_DIR_NAMES = {
    # Version control & development
    ".git", ".svn", ".hg", ".venv", "venv", "env", "__pycache__",
    "node_modules", ".cache", ".npm", ".yarn", ".cargo", ".rustup",
    ".gradle", ".m2", "target", "build", "dist", ".tox",
    ".idea", ".vscode", ".vs",

    # Windows system & metadata directories
    "$recycle.bin", "$winre_backup_partition.marker", "system volume information",
    "windows", "program files", "program files (x86)", "programdata",
    "msocache", "perflogs", "recovery", "appdata",
}

# Root-level folder prefixes to skip when scanning drive roots (e.g. C:\ or D:\)
WINDOWS_DRIVE_ROOT_IGNORES = {
    "windows", "program files", "program files (x86)", "programdata",
    "$recycle.bin", "system volume information", "recovery", "msocache",
    "perflogs", "documents and settings",
}

# System files on drive roots that should not be scanned
WINDOWS_ROOT_SYSTEM_FILES = {
    "pagefile.sys", "hiberfil.sys", "swapfile.sys", "dumpstack.log.tmp"
}


def is_windows_drive_root(path: Union[Path, str]) -> bool:
    """Check if path is a drive root like 'C:\\' or 'D:\\'."""
    p = Path(path).resolve()
    return p.parent == p or str(p).rstrip("\\/").endswith(":")


def is_system_ignored_path(dirpath: str, is_root_scan: bool) -> bool:
    """Determine if a directory should be skipped during scanning."""
    p = Path(dirpath)
    name_lower = p.name.lower()

    if name_lower in IGNORED_DIR_NAMES:
        return True

    if is_root_scan:
        # Check if dir is directly under drive root and matches root ignores
        drive, rest = os.path.splitdrive(str(p.resolve()))
        parts = [part.lower() for part in Path(rest).parts if part not in ("\\", "/")]
        if parts and parts[0] in WINDOWS_DRIVE_ROOT_IGNORES:
            return True

    return False


def parse_size_bytes(val: Union[str, int, float, None]) -> Optional[int]:
    """Parse human readable size string like '50KB', '100MB', '4GB' into bytes."""
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
