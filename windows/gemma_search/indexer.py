"""Persistent SQLite indexer supporting major-type filtering, size bounds, and fast vector search (Windows)."""

import os
import sqlite3
import hashlib
import time
import gc
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
import numpy as np
import torch

from gemma_search.config import (
    DEFAULT_DB_PATH,
    DEFAULT_MIN_FILE_SIZE_BYTES,
    DEFAULT_MAX_FILE_SIZE_BYTES,
    DEFAULT_MAX_VIDEO_SIZE_BYTES,
    MAJOR_EXTENSIONS,
    ALL_SUPPORTED_EXTENSIONS,
    IGNORED_DIR_NAMES,
    WINDOWS_DRIVE_ROOT_IGNORES,
    WINDOWS_ROOT_SYSTEM_FILES,
    is_windows_drive_root,
    is_system_ignored_path,
)
from gemma_search.extractors import extract_file_data, detect_modality
from gemma_search.model import load_model, encode_query, encode_item


def compute_fingerprint(file_path: Path) -> str:
    """Fast file fingerprint using size, mtime, and sample blake2b hash."""
    try:
        st = file_path.stat()
        size = st.st_size
        mtime = st.st_mtime
        hasher = hashlib.blake2b(digest_size=16)
        hasher.update(f"{size}:{mtime}".encode("utf-8"))

        with open(file_path, "rb") as f:
            if size <= 131072:
                hasher.update(f.read())
            else:
                hasher.update(f.read(65536))
                f.seek(max(0, size - 65536))
                hasher.update(f.read(65536))
        return hasher.hexdigest()
    except Exception:
        try:
            st = file_path.stat()
            return f"{st.st_size}:{st.st_mtime}"
        except (OSError, PermissionError):
            return ""


class SearchResult:
    def __init__(
        self,
        abs_path: str,
        modality: str,
        score: float,
        preview: str,
        size_bytes: int,
        indexed_at: float = 0.0,
        filename: Optional[str] = None,
        **kwargs,
    ):
        self.abs_path = abs_path
        self.filename = filename or Path(abs_path).name
        self.modality = modality
        self.score = float(score)
        self.preview = preview
        self.size_bytes = size_bytes
        self.indexed_at = indexed_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "abs_path": self.abs_path,
            "filename": self.filename,
            "modality": self.modality,
            "score": round(self.score, 4),
            "preview": self.preview,
            "size_bytes": self.size_bytes,
            "indexed_at": self.indexed_at,
        }


class GlobalIndex:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or DEFAULT_DB_PATH).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initialize SQLite tables for persistent records."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS records (
                    abs_path TEXT PRIMARY KEY,
                    fingerprint TEXT,
                    file_size INTEGER,
                    mtime REAL,
                    modality TEXT,
                    preview TEXT,
                    indexed_at REAL,
                    embedding BLOB
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_records_path ON records(abs_path)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_records_modality ON records(modality)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_records_size ON records(file_size)")
            conn.commit()

    def get_existing_fingerprints(self, path_filter: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
        """Fetch indexed paths and fingerprints for fast change detection."""
        query = "SELECT abs_path, fingerprint, file_size, mtime FROM records"
        params = []
        if path_filter:
            prefix = str(Path(path_filter).resolve())
            if not prefix.endswith(("\\", "/")):
                prefix += "\\"
            query += " WHERE abs_path LIKE ?"
            params.append(prefix + "%")

        with self._get_connection() as conn:
            cur = conn.execute(query, params)
            rows = cur.fetchall()
            return {
                r["abs_path"]: {
                    "fingerprint": r["fingerprint"],
                    "file_size": r["file_size"],
                    "mtime": r["mtime"],
                }
                for r in rows
            }

    def scan_and_index(
        self,
        root_path: Path,
        min_size_bytes: int = DEFAULT_MIN_FILE_SIZE_BYTES,
        max_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES,
        max_video_size_bytes: int = DEFAULT_MAX_VIDEO_SIZE_BYTES,
        allowed_exts: Optional[Set[str]] = MAJOR_EXTENSIONS,
        force: bool = False,
        prune_missing: bool = False,
        progress_callback: Optional[callable] = None,
    ) -> Dict[str, int]:
        """Scan directory and index files matching type and size filters.
        
        By default:
        - Only major types are scanned (mp4, mp3, wav, jpg, png, etc.)
        - Size bounds: 50 KB to 100 MB (up to 4 GB for videos)
        - Windows system paths, Recycle Bin, and system files are ignored.
        - Unchanged files are preserved from SQLite records without re-embedding.
        """
        root = Path(root_path).resolve()
        is_root_scan = is_windows_drive_root(root)
        existing_map = self.get_existing_fingerprints(path_filter=None if is_root_scan else root)

        to_process = []
        found_paths: Set[str] = set()

        unchanged_count = 0
        skipped_small_count = 0
        skipped_large_count = 0
        skipped_type_count = 0
        new_count = 0
        mod_count = 0

        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            # Skip system / ignored directories
            if is_system_ignored_path(dirpath, is_root_scan=is_root_scan):
                dirnames[:] = []
                continue

            # Filter out ignored child directories and Windows junctions
            clean_dirs = []
            for d in dirnames:
                d_lower = d.lower()
                if d_lower in IGNORED_DIR_NAMES or d.startswith(".gemma_"):
                    continue
                # Skip reparse points / junctions to prevent infinite loops
                child_path = os.path.join(dirpath, d)
                try:
                    if os.path.islink(child_path) or (hasattr(os.path, "isjunction") and os.path.isjunction(child_path)):
                        continue
                except (OSError, PermissionError):
                    continue
                clean_dirs.append(d)
            dirnames[:] = clean_dirs

            for fname in filenames:
                fname_lower = fname.lower()
                if fname_lower.startswith(".gemma_") or fname_lower.startswith(".records."):
                    continue
                if is_root_scan and fname_lower in WINDOWS_ROOT_SYSTEM_FILES:
                    continue

                fpath = Path(dirpath) / fname
                abs_str = str(fpath.resolve())
                found_paths.add(abs_str)

                suffix = fpath.suffix.lower()

                # 1. Filter by extension
                if allowed_exts is not None and suffix not in allowed_exts:
                    skipped_type_count += 1
                    continue

                try:
                    st = fpath.stat()
                    size = st.st_size
                    mtime = st.st_mtime
                except (OSError, PermissionError):
                    continue

                # 2. Detect modality
                modality = detect_modality(fpath, allowed_exts=allowed_exts)
                if modality == "unsupported":
                    skipped_type_count += 1
                    continue

                # 3. Filter by size boundaries (50 KB - 100 MB, up to 4 GB for videos)
                effective_max = max_video_size_bytes if modality == "video" else max_size_bytes
                if size < min_size_bytes:
                    skipped_small_count += 1
                    continue
                if size > effective_max:
                    skipped_large_count += 1
                    continue

                # 4. Check if already recorded & unchanged
                fp = compute_fingerprint(fpath)
                if not force and abs_str in existing_map:
                    old_meta = existing_map[abs_str]
                    if old_meta["fingerprint"] == fp:
                        unchanged_count += 1
                        continue
                    else:
                        mod_count += 1
                else:
                    new_count += 1

                to_process.append((fpath, abs_str, fp, size, mtime, modality))

        removed_count = 0
        if prune_missing:
            missing_paths = set(existing_map.keys()) - found_paths
            if missing_paths:
                with self._get_connection() as conn:
                    for mp in missing_paths:
                        conn.execute("DELETE FROM records WHERE abs_path = ?", (mp,))
                    conn.commit()
                removed_count = len(missing_paths)

        if not to_process:
            return {
                "total": self.count_records(path_filter=None if is_root_scan else root),
                "new": 0,
                "modified": 0,
                "unchanged": unchanged_count,
                "skipped_small": skipped_small_count,
                "skipped_large": skipped_large_count,
                "skipped_type": skipped_type_count,
                "removed": removed_count,
            }

        # Embed only the files that need indexing
        model = load_model()

        with self._get_connection() as conn:
            for i, (path, abs_str, fp, size, mtime, modality) in enumerate(to_process):
                if progress_callback:
                    progress_callback(i + 1, len(to_process), path.name)

                data = extract_file_data(
                    path,
                    min_size_bytes=min_size_bytes,
                    max_size_bytes=max_size_bytes,
                    max_video_size_bytes=max_video_size_bytes,
                    allowed_exts=allowed_exts,
                )
                if data is None:
                    continue

                mod, payload, preview = data
                try:
                    vec = encode_item(payload, model=model)
                    vec_blob = vec.astype(np.float32).tobytes()

                    conn.execute("""
                        INSERT INTO records (
                            abs_path, fingerprint, file_size, mtime,
                            modality, preview, indexed_at, embedding
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(abs_path) DO UPDATE SET
                            fingerprint=excluded.fingerprint,
                            file_size=excluded.file_size,
                            mtime=excluded.mtime,
                            modality=excluded.modality,
                            preview=excluded.preview,
                            indexed_at=excluded.indexed_at,
                            embedding=excluded.embedding
                    """, (abs_str, fp, size, mtime, mod, preview, time.time(), vec_blob))

                    if (i + 1) % 25 == 0:
                        conn.commit()
                        gc.collect()
                        if torch.cuda.is_available():
                            torch.cuda.empty_cache()

                except Exception:
                    continue

            conn.commit()

        return {
            "total": self.count_records(path_filter=None if is_root_scan else root),
            "new": new_count,
            "modified": mod_count,
            "unchanged": unchanged_count,
            "skipped_small": skipped_small_count,
            "skipped_large": skipped_large_count,
            "skipped_type": skipped_type_count,
            "removed": removed_count,
        }

    def count_records(self, path_filter: Optional[Path] = None) -> int:
        """Count indexed files."""
        query = "SELECT COUNT(*) FROM records"
        params = []
        if path_filter:
            prefix = str(Path(path_filter).resolve())
            if not prefix.endswith(("\\", "/")):
                prefix += "\\"
            query += " WHERE abs_path LIKE ?"
            params.append(prefix + "%")

        with self._get_connection() as conn:
            cur = conn.execute(query, params)
            return cur.fetchone()[0]

    def load_vectors(
        self,
        path_filter: Optional[Path] = None,
        type_filter: Optional[str] = None,
        ext_filter: Optional[Set[str]] = None,
        min_size_bytes: Optional[int] = None,
        max_size_bytes: Optional[int] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[np.ndarray]]:
        """Load metadata and embeddings from SQLite into memory with optional filters."""
        query_sql = "SELECT abs_path, modality, preview, file_size, indexed_at, embedding FROM records"
        conditions = []
        params = []

        if path_filter:
            prefix = str(Path(path_filter).resolve())
            if not prefix.endswith(("\\", "/")):
                prefix += "\\"
            conditions.append("abs_path LIKE ?")
            params.append(prefix + "%")

        if type_filter:
            conditions.append("modality = ?")
            params.append(type_filter.lower())

        if ext_filter:
            ext_clauses = ["abs_path LIKE ?" for _ in ext_filter]
            conditions.append(f"({' OR '.join(ext_clauses)})")
            for ext in ext_filter:
                clean_ext = ext if ext.startswith(".") else f".{ext}"
                params.append(f"%{clean_ext.lower()}")

        if min_size_bytes is not None:
            conditions.append("file_size >= ?")
            params.append(min_size_bytes)

        if max_size_bytes is not None:
            conditions.append("file_size <= ?")
            params.append(max_size_bytes)

        if conditions:
            query_sql += " WHERE " + " AND ".join(conditions)

        with self._get_connection() as conn:
            cur = conn.execute(query_sql, params)
            rows = cur.fetchall()

        if not rows:
            return [], None

        records = []
        blobs = []
        for r in rows:
            records.append({
                "abs_path": r["abs_path"],
                "modality": r["modality"],
                "preview": r["preview"],
                "file_size": r["file_size"],
                "indexed_at": r["indexed_at"],
            })
            blobs.append(r["embedding"])

        stacked = b"".join(blobs)
        embeddings = np.frombuffer(stacked, dtype=np.float32).reshape(len(records), 768)
        return records, embeddings

    def search(
        self,
        query: str,
        path_filter: Optional[Path] = None,
        type_filter: Optional[str] = None,
        ext_filter: Optional[Set[str]] = None,
        min_size_bytes: Optional[int] = None,
        max_size_bytes: Optional[int] = None,
        top_k: int = 5,
        min_score: float = -1.0,
        query_vec: Optional[np.ndarray] = None,
    ) -> List[SearchResult]:
        """Search records via vector similarity with optional filters."""
        records, embeddings = self.load_vectors(
            path_filter=path_filter,
            type_filter=type_filter,
            ext_filter=ext_filter,
            min_size_bytes=min_size_bytes,
            max_size_bytes=max_size_bytes,
        )
        if not records or embeddings is None:
            return []

        if query_vec is None:
            query_vec = encode_query(query)

        scores = np.dot(embeddings, query_vec)
        ranked_indices = np.argsort(scores)[::-1]

        results = []
        for idx in ranked_indices:
            score = float(scores[idx])
            if score < min_score:
                continue
            rec = records[idx]
            results.append(
                SearchResult(
                    abs_path=rec["abs_path"],
                    modality=rec["modality"],
                    score=score,
                    preview=rec["preview"],
                    size_bytes=rec["file_size"],
                    indexed_at=rec["indexed_at"],
                )
            )
            if len(results) >= top_k:
                break

        return results

    def list_records(self, path_filter: Optional[Path] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """List stored records."""
        query = "SELECT abs_path, modality, file_size, preview, indexed_at FROM records"
        params = []
        if path_filter:
            prefix = str(Path(path_filter).resolve())
            if not prefix.endswith(("\\", "/")):
                prefix += "\\"
            query += " WHERE abs_path LIKE ?"
            params.append(prefix + "%")
        query += " ORDER BY indexed_at DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            cur = conn.execute(query, params)
            return [dict(r) for r in cur.fetchall()]

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregate index statistics."""
        with self._get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            cur = conn.execute("SELECT modality, COUNT(*) FROM records GROUP BY modality")
            mod_counts = {r[0]: r[1] for r in cur.fetchall()}

        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            "total_files": total,
            "modalities": mod_counts,
            "db_size_bytes": db_size,
            "db_path": str(self.db_path),
        }

    def clear(self, path_filter: Optional[Path] = None) -> int:
        """Clear database records."""
        with self._get_connection() as conn:
            if path_filter:
                prefix = str(Path(path_filter).resolve())
                if not prefix.endswith(("\\", "/")):
                    prefix += "\\"
                cur = conn.execute("DELETE FROM records WHERE abs_path LIKE ?", (prefix + "%",))
            else:
                cur = conn.execute("DELETE FROM records")
            conn.commit()
            deleted = cur.rowcount
            conn.execute("VACUUM")
            return deleted
