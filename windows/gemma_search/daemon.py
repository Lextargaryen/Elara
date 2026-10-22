"""Background GPU Inference Daemon with TCP loopback IPC for Windows."""

import os
import sys
import json
import time
import signal
import socket
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any

from gemma_search.config import (
    PID_PATH,
    PORT_PATH,
    LOCK_PATH,
    DAEMON_HOST,
    DEFAULT_DAEMON_PORT,
)


def acquire_process_lock() -> Optional[Any]:
    """Acquire single-instance file lock cross-platform (using msvcrt on Windows, fcntl on Unix)."""
    Path(LOCK_PATH).parent.mkdir(parents=True, exist_ok=True)
    try:
        lock_file = open(LOCK_PATH, "a+")
        if sys.platform == "win32":
            import msvcrt
            try:
                lock_file.seek(0, os.SEEK_END)
                if lock_file.tell() == 0:
                    lock_file.write("1\n")
                    lock_file.flush()
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                return lock_file
            except (BlockingIOError, OSError):
                lock_file.close()
                return None
        else:
            import fcntl
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return lock_file
            except (BlockingIOError, OSError):
                lock_file.close()
                return None
    except Exception:
        return None


def release_process_lock(lock_file: Any):
    """Release single-instance lock."""
    if lock_file is None:
        return
    try:
        if sys.platform == "win32":
            import msvcrt
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()
    except Exception:
        pass


def _cleanup_files():
    """Remove stale PID and Port files."""
    for p in (PORT_PATH, PID_PATH):
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


def get_daemon_port() -> Optional[int]:
    """Read the active daemon port from PORT_PATH."""
    if not os.path.exists(PORT_PATH):
        return None
    try:
        with open(PORT_PATH, "r") as f:
            return int(f.read().strip())
    except (ValueError, OSError):
        return None


def is_daemon_running() -> Optional[int]:
    """Check if background daemon is actively running and responsive over TCP loopback."""
    if not os.path.exists(PID_PATH):
        return None

    try:
        with open(PID_PATH, "r") as f:
            pid = int(f.read().strip())
    except (ValueError, OSError):
        return None

    port = get_daemon_port()
    if not port:
        return None

    # Ping the daemon via loopback TCP socket
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(1.0)
        client.connect((DAEMON_HOST, port))
        client.sendall(json.dumps({"action": "ping"}).encode("utf-8") + b"\n")
        res = client.recv(1024)
        client.close()
        if res:
            data = json.loads(res.decode("utf-8").strip())
            if data.get("status") == "ok":
                return pid
    except Exception:
        _cleanup_files()
        return None

    return None


def send_daemon_request(payload: Dict[str, Any], timeout: float = 30.0) -> Optional[Dict[str, Any]]:
    """Send JSON request to daemon via loopback TCP and receive JSON response."""
    port = get_daemon_port()
    if not port:
        return None

    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect((DAEMON_HOST, port))

        data = json.dumps(payload).encode("utf-8") + b"\n"
        client.sendall(data)

        chunks = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if chunk.endswith(b"\n"):
                break
        client.close()

        if not chunks:
            return None

        raw = b"".join(chunks).decode("utf-8").strip()
        return json.loads(raw)
    except Exception:
        return None


def run_daemon_server():
    """Main daemon server loop. Preloads model in GPU memory and serves queries over TCP loopback."""
    lock_file = acquire_process_lock()
    if lock_file is None:
        # Another daemon is already holding the lock
        sys.exit(0)

    _cleanup_files()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    port = DEFAULT_DAEMON_PORT
    try:
        server.bind((DAEMON_HOST, port))
    except OSError:
        # If default port is taken, bind to ephemeral port
        server.bind((DAEMON_HOST, 0))
        port = server.getsockname()[1]

    server.listen(10)

    with open(PID_PATH, "w") as f:
        f.write(str(os.getpid()))

    with open(PORT_PATH, "w") as f:
        f.write(str(port))

    from gemma_search.model import load_model, encode_query, get_device_info
    from gemma_search.indexer import GlobalIndex

    dev_info = get_device_info()
    model = load_model(verbose=False)
    index = GlobalIndex()

    def shutdown_handler(signum, frame):
        try:
            server.close()
        except Exception:
            pass
        _cleanup_files()
        release_process_lock(lock_file)
        sys.exit(0)

    try:
        signal.signal(signal.SIGTERM, shutdown_handler)
    except Exception:
        pass
    try:
        signal.signal(signal.SIGINT, shutdown_handler)
    except Exception:
        pass

    while True:
        try:
            conn, _ = server.accept()
            conn.settimeout(60.0)
            data_buf = []
            while True:
                chunk = conn.recv(16384)
                if not chunk:
                    break
                data_buf.append(chunk)
                if chunk.endswith(b"\n"):
                    break

            if not data_buf:
                conn.close()
                continue

            msg = json.loads(b"".join(data_buf).decode("utf-8").strip())
            action = msg.get("action")

            if action == "ping":
                reply = {"status": "ok", "device": dev_info["device_desc"]}

            elif action == "stop":
                conn.sendall(json.dumps({"status": "stopping"}).encode("utf-8") + b"\n")
                conn.close()
                break

            elif action == "search":
                t0 = time.time()
                query = msg["query"]
                path_filter = Path(msg["path_filter"]) if msg.get("path_filter") else None
                type_filter = msg.get("type_filter")
                ext_filter = set(msg["ext_filter"]) if msg.get("ext_filter") else None
                min_size_bytes = msg.get("min_size_bytes")
                max_size_bytes = msg.get("max_size_bytes")
                top_k = msg.get("top_k", 5)
                min_score = msg.get("min_score", -1.0)

                q_vec = encode_query(query, model=model)
                results = index.search(
                    query,
                    path_filter=path_filter,
                    type_filter=type_filter,
                    ext_filter=ext_filter,
                    min_size_bytes=min_size_bytes,
                    max_size_bytes=max_size_bytes,
                    top_k=top_k,
                    min_score=min_score,
                    query_vec=q_vec,
                )
                dt = time.time() - t0

                reply = {
                    "status": "ok",
                    "results": [r.to_dict() for r in results],
                    "time_sec": dt,
                }

            elif action == "encode":
                text = msg["text"]
                q_vec = encode_query(text, model=model)
                reply = {
                    "status": "ok",
                    "vector": q_vec.tolist(),
                }
            else:
                reply = {"status": "error", "message": f"Unknown action: {action}"}

            conn.sendall(json.dumps(reply).encode("utf-8") + b"\n")
            conn.close()

        except Exception as e:
            try:
                conn.sendall(json.dumps({"status": "error", "message": str(e)}).encode("utf-8") + b"\n")
                conn.close()
            except Exception:
                pass

    _cleanup_files()
    release_process_lock(lock_file)


def start_daemon_process() -> bool:
    """Start daemon in background detached process on Windows."""
    if is_daemon_running():
        return True

    _cleanup_files()
    script_dir = Path(__file__).resolve().parent.parent

    # Detect Python binary
    python_candidates = [
        script_dir / ".venv" / "Scripts" / "python.exe",
        script_dir / ".venv" / "bin" / "python3",
        Path(sys.executable),
    ]
    python_bin = str(sys.executable)
    for c in python_candidates:
        if c.exists():
            python_bin = str(c)
            break

    cmd = [python_bin, "-c", f"import sys; sys.path.insert(0, r'{script_dir}'); from gemma_search.daemon import run_daemon_server; run_daemon_server()"]

    # On Windows, use CREATE_NO_WINDOW and DETACHED_PROCESS so no console appears
    kwargs = {
        "cwd": str(script_dir),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        # DETACHED_PROCESS = 0x00000008, CREATE_NO_WINDOW = 0x08000000
        kwargs["creationflags"] = 0x08000000 | 0x00000008
    else:
        kwargs["start_new_session"] = True

    subprocess.Popen(cmd, **kwargs)

    # Wait up to 30s for model to load and daemon to accept queries
    for _ in range(60):
        time.sleep(0.5)
        if is_daemon_running():
            return True

    return False


def stop_daemon_process() -> bool:
    """Stop the running daemon cleanly."""
    pid = is_daemon_running()
    if not pid:
        _cleanup_files()
        return True

    try:
        send_daemon_request({"action": "stop"}, timeout=2.0)
    except Exception:
        pass

    # Wait up to 3 seconds for graceful shutdown
    for _ in range(30):
        time.sleep(0.1)
        if not is_daemon_running():
            _cleanup_files()
            return True

    # Force terminate if still unresponsive
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception:
        pass

    _cleanup_files()
    return True
