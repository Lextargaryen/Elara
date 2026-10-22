import os
import sys
import json
import time
import signal
import socket
import fcntl
from pathlib import Path
from typing import Optional, Dict, Any

from gemma_search.config import SOCKET_PATH, PID_PATH, LOCK_PATH


def is_daemon_running() -> Optional[int]:
    """Check if background daemon is actively running and responsive."""
    if not os.path.exists(PID_PATH):
        return None

    try:
        with open(PID_PATH, "r") as f:
            pid = int(f.read().strip())
    except (ValueError, OSError):
        return None

    try:
        os.kill(pid, 0)
    except OSError:
        _cleanup_files()
        return None

    # Check if process is responsive via socket
    if os.path.exists(SOCKET_PATH):
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(1.0)
            client.connect(SOCKET_PATH)
            client.sendall(json.dumps({"action": "ping"}).encode("utf-8") + b"\n")
            res = client.recv(1024)
            client.close()
            if res:
                return pid
        except Exception:
            pass

    return pid


def _cleanup_files():
    if os.path.exists(SOCKET_PATH):
        try:
            os.remove(SOCKET_PATH)
        except OSError:
            pass
    if os.path.exists(PID_PATH):
        try:
            os.remove(PID_PATH)
        except OSError:
            pass



def send_daemon_request(payload: Dict[str, Any], timeout: float = 30.0) -> Optional[Dict[str, Any]]:
    """Send JSON request to daemon and receive JSON response."""
    if not os.path.exists(SOCKET_PATH):
        return None

    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(SOCKET_PATH)

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
    """Main daemon server loop. Preloads model in GPU memory and serves queries."""
    Path(LOCK_PATH).parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        # Another daemon instance is already active
        sys.exit(0)

    _cleanup_files()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    server.listen(10)

    with open(PID_PATH, "w") as f:
        f.write(str(os.getpid()))

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
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)


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


def start_daemon_process() -> bool:
    """Start daemon in background detached process."""
    if is_daemon_running():
        return True

    _cleanup_files()
    script_dir = Path(__file__).resolve().parent.parent
    venv_python = script_dir / ".venv" / "bin" / "python3"
    python_bin = str(venv_python) if venv_python.exists() else sys.executable

    import subprocess
    cmd = [python_bin, "-c", "from gemma_search.daemon import run_daemon_server; run_daemon_server()"]

    subprocess.Popen(
        cmd,
        cwd=str(script_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    # Wait up to 30s for model to load and daemon to become ready
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
        try:
            os.kill(pid, 0)
            time.sleep(0.1)
        except OSError:
            break
    else:
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.2)
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

    _cleanup_files()
    return True

