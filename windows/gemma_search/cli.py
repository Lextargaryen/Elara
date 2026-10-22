"""Minimalistic Windows CLI interface for Elara Multimodal Semantic Search."""

import os
import sys
import time
import argparse
import subprocess
from pathlib import Path
from typing import Optional, List, Set, Union

# Enable Virtual Terminal Processing for TrueColor ANSI on Windows ConHost
if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        h_out = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(h_out, ctypes.byref(mode)):
            kernel32.SetConsoleMode(h_out, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.text import Text

from gemma_search.config import (
    DATA_DIR,
    DEFAULT_MIN_FILE_SIZE_BYTES,
    DEFAULT_MAX_FILE_SIZE_BYTES,
    DEFAULT_MAX_VIDEO_SIZE_BYTES,
    MAJOR_EXTENSIONS,
    ALL_SUPPORTED_EXTENSIONS,
    MAJOR_VIDEO_EXTS,
    MAJOR_AUDIO_EXTS,
    MAJOR_IMAGE_EXTS,
    MAJOR_DOC_EXTS,
    CODE_EXTS,
    parse_size_bytes,
    format_bytes,
)
from gemma_search.indexer import GlobalIndex, SearchResult
from gemma_search.model import get_device_info, load_model
from gemma_search.daemon import (
    is_daemon_running,
    send_daemon_request,
    start_daemon_process,
    stop_daemon_process,
)

_detected_cs = Console().color_system
console = Console(color_system=_detected_cs or "truecolor")

MODALITY_STYLES = {
    "image": ("IMAGE", "bold blue"),
    "video": ("VIDEO", "bold magenta"),
    "audio": ("AUDIO", "bold yellow"),
    "pdf":   ("PDF",   "bold red"),
    "text":  ("DOC",   "bold green"),
    "code":  ("CODE",  "bold cyan"),
}

MODALITY_TYPE_MAP = {
    "image": MAJOR_IMAGE_EXTS,
    "video": MAJOR_VIDEO_EXTS,
    "audio": MAJOR_AUDIO_EXTS,
    "doc":   MAJOR_DOC_EXTS,
    "text":  MAJOR_DOC_EXTS,
    "code":  CODE_EXTS,
}


def render_score_bar(score: float, width: int = 8) -> str:
    """Render a gradient visual confidence bar with percentage."""
    clamped = max(0.0, min(1.0, (score + 1.0) / 2.0))
    filled = int(round(clamped * width))
    empty = width - filled

    if clamped >= 0.75:
        bar = f"[green]{'■' * filled}[/][dim]{'·' * empty}[/]"
    elif clamped >= 0.50:
        bar = f"[cyan]{'■' * filled}[/][dim]{'·' * empty}[/]"
    elif clamped >= 0.30:
        bar = f"[yellow]{'■' * filled}[/][dim]{'·' * empty}[/]"
    else:
        bar = f"[red]{'■' * filled}[/][dim]{'·' * empty}[/]"

    pct = f"{clamped * 100:.1f}%"
    return f"{bar}  {pct}"


def display_results(results: List[SearchResult], query: str, duration_sec: float, quiet: bool = False):
    """Render ranked search results in a Rich table."""
    if quiet:
        for res in results:
            sys.stdout.write(f"{res.abs_path}\n")
        sys.stdout.flush()
        return

    if not results:
        console.print(f"[yellow]No matches found for:[/] [italic]{query}[/]")
        return

    time_str = f"{duration_sec * 1000:.1f}ms" if duration_sec < 1.0 else f"{duration_sec:.2f}s"
    table = Table(
        title=f"Search: \"{query}\" ({len(results)} matches in {time_str})",
        header_style="bold cyan",
        border_style="dim",
        expand=True,
    )

    table.add_column("#", justify="right", width=3, style="bold")
    table.add_column("Score", width=17)
    table.add_column("Type", width=7, justify="center")
    table.add_column("File / Details", ratio=3)
    table.add_column("Size", width=9, justify="right", style="dim")

    for i, res in enumerate(results, 1):
        type_label, type_style = MODALITY_STYLES.get(res.modality, ("FILE", "white"))
        type_badge = f"[{type_style}]{type_label}[/]"
        score_bar = render_score_bar(res.score)

        details = Text()
        details.append(f"{res.filename}\n", style="bold white underline")
        details.append(f"  ➜ {res.abs_path}\n", style="dim blue")
        details.append(f"  {res.preview}", style="italic dim")

        table.add_row(
            str(i),
            score_bar,
            type_badge,
            details,
            format_bytes(res.size_bytes),
        )

    console.print(table)
    console.print(f"[dim]Top match:[/] [bold underline green]{results[0].abs_path}[/]\n")


def parse_extensions_arg(ext_str: Optional[str], type_str: Optional[str], all_types: bool) -> Optional[Set[str]]:
    """Determine allowed extensions from CLI arguments."""
    if all_types:
        return None

    allowed = set()
    if type_str:
        t_clean = type_str.lower().strip()
        if t_clean in MODALITY_TYPE_MAP:
            allowed |= MODALITY_TYPE_MAP[t_clean]

    if ext_str:
        parts = [p.strip().lower() for p in ext_str.split(",") if p.strip()]
        for p in parts:
            allowed.add(p if p.startswith(".") else f".{p}")

    if allowed:
        return allowed

    return set(MAJOR_EXTENSIONS)


def cmd_scan(args):
    """Scan and index a directory or full disk with size and type filters."""
    target_dir = Path(args.path).resolve()
    if not target_dir.exists():
        console.print(f"[bold red]Error:[/] Path '{target_dir}' does not exist.")
        sys.exit(1)

    # Size limits (default: 50 KB - 100 MB, up to 4 GB for videos)
    if getattr(args, "no_size_limit", False):
        min_size_bytes = 0
        max_size_bytes = 999999999999
        max_video_size_bytes = 999999999999
    else:
        min_size_bytes = parse_size_bytes(args.min_size) if args.min_size else DEFAULT_MIN_FILE_SIZE_BYTES
        max_size_bytes = parse_size_bytes(args.max_size) if args.max_size else DEFAULT_MAX_FILE_SIZE_BYTES
        max_video_size_bytes = parse_size_bytes(getattr(args, "max_video_size", None)) or DEFAULT_MAX_VIDEO_SIZE_BYTES

    # Extensions
    allowed_exts = parse_extensions_arg(
        ext_str=getattr(args, "ext", None),
        type_str=getattr(args, "type", None),
        all_types=getattr(args, "all_types", False),
    )

    type_desc = "All Types" if allowed_exts is None else f"Major ({len(allowed_exts)} types: mp4, mp3, wav, jpg, png...)"
    size_desc = f"{format_bytes(min_size_bytes)} to {format_bytes(max_size_bytes)} (up to {format_bytes(max_video_size_bytes)} for videos)"

    index = GlobalIndex(db_path=args.db)
    scope_str = str(target_dir)

    console.print(f"[bold cyan]Scanning:[/] {scope_str}")
    console.print(f"[dim]• Types: {type_desc}\n• Size Range: {size_desc}[/]")

    was_daemon_running = bool(is_daemon_running())
    if was_daemon_running:
        console.print("[dim]Pausing background daemon to prioritize memory for scanning...[/]")
        stop_daemon_process()

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Indexing...", total=None)

            def cb(current, total, filename):
                progress.update(task, total=total, completed=current, description=f"Embedding: [bold]{filename}[/]")

            t0 = time.time()
            counts = index.scan_and_index(
                root_path=target_dir,
                min_size_bytes=min_size_bytes,
                max_size_bytes=max_size_bytes,
                max_video_size_bytes=max_video_size_bytes,
                allowed_exts=allowed_exts,
                force=args.force,
                prune_missing=args.prune,
                progress_callback=cb,
            )
            elapsed = time.time() - t0
    finally:
        if was_daemon_running:
            console.print("[dim]Resuming background search daemon...[/]")
            start_daemon_process()

    console.print(
        f"[green]✓ Done in {elapsed:.2f}s![/] "
        f"([bold]{counts['total']}[/] total records: "
        f"[green]+{counts['new']} new[/], "
        f"[yellow]~{counts['modified']} modified[/], "
        f"[cyan]{counts['unchanged']} kept from records[/], "
        f"[dim]{counts['skipped_small']} skipped <{format_bytes(min_size_bytes)}[/], "
        f"[dim]{counts['skipped_large']} skipped >limits[/], "
        f"[dim]{counts['skipped_type']} skipped non-target type[/])"
    )


def cmd_search(query: Union[str, List[str]], args):
    """Execute semantic search against database, with optional live scan and type/size filters."""
    if isinstance(query, (list, tuple)):
        query = " ".join(str(q) for q in query)

    index = GlobalIndex(db_path=args.db)
    path_filter = Path(args.path).resolve() if args.path else None

    min_size_bytes = parse_size_bytes(args.min_size) if getattr(args, "min_size", None) else None
    max_size_bytes = parse_size_bytes(args.max_size) if getattr(args, "max_size", None) else None

    type_filter = getattr(args, "type", None)
    ext_arg = getattr(args, "ext", None)
    ext_filter = set()
    if ext_arg:
        for e in ext_arg.split(","):
            e = e.strip().lower()
            if e:
                ext_filter.add(e if e.startswith(".") else f".{e}")

    # If --scan override requested, scan the target path first
    if getattr(args, "scan", False):
        scan_dir = path_filter or Path(".")
        console.print(f"[cyan]Scanning {scan_dir} before search...[/]")
        cmd_scan(argparse.Namespace(
            path=str(scan_dir),
            min_size=args.min_size,
            max_size=args.max_size,
            max_video_size=getattr(args, "max_video_size", "4GB"),
            no_size_limit=getattr(args, "no_size_limit", False),
            ext=args.ext,
            type=args.type,
            all_types=getattr(args, "all_types", False),
            force=False,
            prune=False,
            db=args.db,
        ))

    total_records = index.count_records(path_filter=path_filter)
    if total_records == 0:
        if path_filter:
            console.print(f"[yellow]No records found for path:[/] {path_filter}\n"
                          f"Run: [bold]elara scan {path_filter}[/bold] or add [bold]--scan[/bold] to search and scan.")
        else:
            console.print("[yellow]No files have been indexed yet.[/]\n"
                          "Run: [bold]elara scan <folder>[/bold] (e.g. [bold]elara scan .[/bold]) first.")
        sys.exit(0)

    # 1. Fast daemon search (<30ms)
    if is_daemon_running():
        res_json = send_daemon_request({
            "action": "search",
            "query": query,
            "path_filter": str(path_filter) if path_filter else None,
            "type_filter": type_filter,
            "ext_filter": list(ext_filter) if ext_filter else None,
            "min_size_bytes": min_size_bytes,
            "max_size_bytes": max_size_bytes,
            "top_k": args.top_k,
            "min_score": args.min_score,
        })
        if res_json and res_json.get("status") == "ok":
            results = [SearchResult(**r) for r in res_json["results"]]
            duration = res_json["time_sec"]

            if args.json:
                import json
                print(json.dumps([r.to_dict() for r in results], indent=2))
            else:
                display_results(results, query, duration, quiet=args.quiet)

            if args.open and results:
                open_file_with_default_app(results[0].abs_path)
            return

    # 2. Standalone fallback (loads model on demand)
    if not args.quiet:
        console.print("[dim]Note: Daemon not running. Loading model (run 'elara daemon start' for <30ms instant searches)...[/]")
    t0 = time.time()
    results = index.search(
        query,
        path_filter=path_filter,
        type_filter=type_filter,
        ext_filter=ext_filter if ext_filter else None,
        min_size_bytes=min_size_bytes,
        max_size_bytes=max_size_bytes,
        top_k=args.top_k,
        min_score=args.min_score,
    )
    duration = time.time() - t0

    if args.json:
        import json
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        display_results(results, query, duration, quiet=args.quiet)
        if not is_daemon_running() and not args.quiet:
            console.print("[dim]Tip: Run [bold]elara daemon start[/bold] for [green]instant (<30ms)[/green] searches![/]\n")

        if args.open and results:
            open_file_with_default_app(results[0].abs_path)


def open_file_with_default_app(file_path: str):
    """Open file using Windows default application."""
    try:
        if sys.platform == "win32":
            os.startfile(file_path)
        else:
            subprocess.Popen(["xdg-open", file_path], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    except Exception as e:
        console.print(f"[dim red]Could not open file:[/] {e}")


def print_banner():
    banner_lines = [
        "  ███████╗██╗      █████╗ ██████╗  █████╗ ",
        "  ██╔════╝██║     ██╔══██╗██╔══██╗██╔══██╗",
        "  █████╗  ██║     ███████║██████╔╝███████║",
        "  ██╔══╝  ██║     ██╔══██║██╔══██╗██╔══██║",
        "  ███████╗███████╗██║  ██║██║  ██║██║  ██║",
        "  ╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝",
    ]
    # Direct 24-bit TrueColor gradient ANSI escape codes (Cyan -> Sky Blue -> Indigo -> Purple -> Violet -> Pink)
    ansi_gradient = [
        "\033[1;38;2;56;189;248m",   # Vibrant Sky Cyan (#38bdf8)
        "\033[1;38;2;96;165;250m",   # Bright Sky Blue (#60a5fa)
        "\033[1;38;2;129;140;248m",  # Vibrant Indigo (#818cf8)
        "\033[1;38;2;167;139;250m",  # Soft Purple (#a78bfa)
        "\033[1;38;2;192;132;252m",  # Bright Violet (#c084fc)
        "\033[1;38;2;232;121;249m",  # Neon Pink / Magenta (#e879f9)
    ]
    for i, line in enumerate(banner_lines):
        sys.stdout.write(f"{ansi_gradient[i]}{line}\033[0m\n")
    sys.stdout.write("  \033[1;37mMultimodal Semantic Search\033[0m \033[38;5;244m• Powered by Google EmbeddingGemma 2 (Windows)\033[0m\n\n")
    sys.stdout.flush()


def display_interactive_help():
    table = Table(title="Elara Commands Reference", header_style="bold cyan", border_style="dim", expand=True)
    table.add_column("Command", style="bold green", width=22)
    table.add_column("Description", ratio=2)
    table.add_column("Examples", style="dim", ratio=2)

    table.add_row(
        "<query>",
        "Search database directly (no keyword needed)",
        "pop music song\nradar scan -t video",
    )
    table.add_row(
        "search <query>",
        "Search with flags (-t type, -e ext, --min-size, --max-size)",
        "search espresso -e mp3\nsearch sunset -t image",
    )
    table.add_row(
        "scan [path]",
        "Scan directory and index files (50KB-100MB, up to 4GB videos, major types)",
        "scan\nscan C:\\Users\\Name\\Downloads -t video",
    )
    table.add_row(
        "records [path]",
        "List all indexed files stored in database",
        "records\nrecords C:\\Users\\Name\\Pictures",
    )
    table.add_row(
        "status",
        "Show index stats, accelerator & daemon status",
        "status",
    )
    table.add_row(
        "daemon <action>",
        "Manage background GPU daemon (start / stop / status)",
        "daemon start\ndaemon stop",
    )
    table.add_row(
        "clean [path]",
        "Clear database records",
        "clean\nclean C:\\Projects",
    )
    table.add_row(
        "clear, cls",
        "Clear terminal screen",
        "clear\ncls",
    )
    table.add_row(
        "exit, quit",
        "Exit Elara and return to terminal",
        "exit",
    )
    console.print(table)


def cmd_records(index: GlobalIndex, path_filter: Optional[str] = None):
    p_filter = Path(path_filter).resolve() if path_filter else None
    recs = index.list_records(path_filter=p_filter, limit=100)
    if not recs:
        console.print("[yellow]No records found in database.[/]")
        return

    table = Table(title=f"Stored Records ({len(recs)} shown)", header_style="bold cyan", border_style="dim", expand=True)
    table.add_column("#", justify="right", width=3)
    table.add_column("Type", width=7, justify="center")
    table.add_column("File / Path", ratio=3)
    table.add_column("Details", ratio=2, style="dim")
    table.add_column("Size", width=9, justify="right")

    for i, r in enumerate(recs, 1):
        type_label, type_style = MODALITY_STYLES.get(r["modality"], ("FILE", "white"))
        type_badge = f"[{type_style}]{type_label}[/]"
        table.add_row(
            str(i),
            type_badge,
            f"[bold]{Path(r['abs_path']).name}[/]\n[dim]{r['abs_path']}[/]",
            r["preview"],
            format_bytes(r["file_size"]),
        )
    console.print(table)


def cmd_status(index: GlobalIndex):
    stats = index.get_stats()
    dev = get_device_info()
    pid = is_daemon_running()

    console.print(Panel(
        f"[bold cyan]Elara Status (Windows)[/]\n\n"
        f"• Database: [green]{stats['db_path']}[/] ({format_bytes(stats['db_size_bytes'])})\n"
        f"• Total Indexed Files: [bold]{stats['total_files']}[/]\n"
        f"• Modality Breakdown:\n" +
        ("\n".join(f"    - {k.capitalize()}: {v}" for k, v in stats['modalities'].items()) if stats['modalities'] else "    - (none)") +
        f"\n\n• Defaults:\n"
        f"    - Size Range: 50 KB to 100 MB (up to 4 GB for videos)\n"
        f"    - File Types: Major (mp4, mp3, wav, jpg, png, webp, pdf, txt, md, docx)\n"
        f"\n• Accelerator: [bold]{dev['device_desc']}[/] ({dev['dtype']})\n"
        f"• Daemon Status: {'[bold green]Running (PID: ' + str(pid) + ')[/]' if pid else '[yellow]Stopped[/] (run elara daemon start)'}",
        title="System Information",
        border_style="cyan"
    ))


def cmd_clean(index: GlobalIndex, path_filter: Optional[str] = None):
    p_filter = Path(path_filter).resolve() if path_filter else None
    deleted = index.clear(path_filter=p_filter)
    console.print(f"[green]Cleared {deleted} records from database.[/]")


def cmd_daemon(action: str):
    if action == "start":
        console.print("[cyan]Starting background search daemon...[/]")
        if start_daemon_process():
            pid = is_daemon_running()
            console.print(f"[bold green]✓ Daemon running (PID: {pid})![/] Fast background queries active.")
        else:
            console.print("[bold red]Failed to start daemon.[/] Check system resources or run standalone.")
    elif action == "stop":
        console.print("[cyan]Stopping background search daemon...[/]")
        stop_daemon_process()
        console.print("[green]Daemon stopped.[/]")
    elif action == "status":
        pid = is_daemon_running()
        if pid:
            console.print(f"[bold green]Daemon running (PID: {pid})[/] on GPU.")
        else:
            console.print("[yellow]Daemon stopped.[/] Start it with: [bold]elara daemon start[/bold]")


def cmd_interactive(args, subparsers_dict=None):
    """Interactive full-terminal REPL for Elara on Windows."""
    import shlex

    readline = None
    try:
        import readline
    except ImportError:
        try:
            import pyreadline3 as readline
        except ImportError:
            readline = None

    hist_file = str(DATA_DIR / "history")
    os.makedirs(os.path.dirname(hist_file), exist_ok=True)
    if readline and os.path.exists(hist_file):
        try:
            readline.read_history_file(hist_file)
        except Exception:
            pass

    COMMANDS = ["search", "scan", "records", "status", "daemon", "clean", "clear", "cls", "help", "exit", "quit"]

    if readline:
        def completer(text, state):
            options = [c for c in COMMANDS if c.startswith(text.lower())]
            if state < len(options):
                return options[state]
            return None

        try:
            readline.set_completer(completer)
            readline.parse_and_bind("tab: complete")
        except Exception:
            pass

    index = GlobalIndex(db_path=getattr(args, "db", None))

    print_banner()

    stats = index.get_stats()
    dev = get_device_info()
    pid = is_daemon_running()
    daemon_tag = f"[bold green]● Daemon Active (PID {pid})[/]" if pid else "[yellow]○ Standalone Mode[/]"

    console.print(
        f"  {daemon_tag} [dim]│[/] "
        f"[cyan]{dev['device_desc']}[/] [dim]│[/] "
        f"[bold]{stats['total_files']}[/] indexed files ({format_bytes(stats['db_size_bytes'])})"
    )
    console.print(
        "  [dim]Commands: [bold white]search[/] <query> [dim]│[/] "
        "[bold white]scan[/] \\[path] [dim]│[/] "
        "[bold white]records[/] \\[path] [dim]│[/] "
        "[bold white]status[/] [dim]│[/] "
        "[bold white]help[/] [dim]│[/] "
        "[bold white]exit[/][/]\n"
        "  [dim]Tip: You can also simply type any search query directly without 'search'.[/]\n"
    )

    while True:
        try:
            prompt_str = "elara > " if sys.platform == "win32" and not os.environ.get("WT_SESSION") else "elara ❯ "
            line = input(prompt_str).strip()
            if not line:
                continue

            if line.lower() in ("exit", "quit", "q"):
                console.print("[dim]👋 Goodbye![/]")
                break

            if line.lower() in ("clear", "cls"):
                os.system("cls" if sys.platform == "win32" else "clear")
                print_banner()
                continue

            if line.lower() in ("help", "?"):
                display_interactive_help()
                continue

            try:
                tokens = shlex.split(line, posix=(sys.platform != "win32"))
            except ValueError as e:
                console.print(f"[red]Input syntax error:[/] {e}")
                continue

            if not tokens:
                continue

            cmd = tokens[0].lower()

            if cmd == "scan":
                if subparsers_dict and "scan" in subparsers_dict:
                    try:
                        scan_args = subparsers_dict["scan"].parse_args(tokens[1:])
                        setattr(scan_args, "db", getattr(args, "db", None))
                        cmd_scan(scan_args)
                    except SystemExit:
                        pass
                else:
                    console.print("[red]Scan parser unavailable[/]")

            elif cmd == "search":
                if subparsers_dict and "search" in subparsers_dict:
                    try:
                        search_args = subparsers_dict["search"].parse_args(tokens[1:])
                        setattr(search_args, "db", getattr(args, "db", None))
                        cmd_search(search_args.query, search_args)
                    except SystemExit:
                        pass
                else:
                    console.print("[red]Search parser unavailable[/]")

            elif cmd == "records":
                path_arg = tokens[1] if len(tokens) > 1 else None
                cmd_records(index, path_arg)

            elif cmd == "status":
                cmd_status(index)

            elif cmd == "clean":
                path_arg = tokens[1] if len(tokens) > 1 else None
                cmd_clean(index, path_arg)

            elif cmd == "daemon":
                action = tokens[1] if len(tokens) > 1 else "status"
                cmd_daemon(action)

            else:
                # Direct query search: user typed query directly without 'search'
                if subparsers_dict and "search" in subparsers_dict:
                    try:
                        search_args = subparsers_dict["search"].parse_args(tokens)
                        setattr(search_args, "db", getattr(args, "db", None))
                        cmd_search(search_args.query, search_args)
                    except SystemExit:
                        fallback_args = argparse.Namespace(
                            db=getattr(args, "db", None),
                            path=None,
                            type=None,
                            ext=None,
                            min_size=None,
                            max_size=None,
                            scan=False,
                            all_types=False,
                            top_k=5,
                            min_score=0.0,
                            open=False,
                            quiet=False,
                            json=False,
                        )
                        cmd_search(line, fallback_args)

        except KeyboardInterrupt:
            print()
            continue
        except EOFError:
            console.print("\n[dim]👋 Goodbye![/]")
            break
        except Exception as e:
            console.print(f"[bold red]Error:[/] {e}")

    if readline:
        try:
            readline.write_history_file(hist_file)
        except Exception:
            pass


def main():
    KNOWN_COMMANDS = {"scan", "search", "records", "status", "clean", "daemon", "interactive"}
    if len(sys.argv) > 1:
        first = sys.argv[1]
        if first in ("-i", "--interactive"):
            sys.argv[1] = "interactive"
        elif first not in KNOWN_COMMANDS and not first.startswith("-"):
            sys.argv.insert(1, "search")
        elif first.startswith("-") and not any(arg in KNOWN_COMMANDS for arg in sys.argv[1:]):
            if not any(h in sys.argv for h in ("-h", "--help")):
                sys.argv.insert(1, "search")

    parser = argparse.ArgumentParser(
        prog="elara",
        description="Elara - Minimalistic Windows Multimodal Semantic Search powered by Google EmbeddingGemma 2.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", type=Path, default=None, help="Custom database path.")

    subparsers = parser.add_subparsers(dest="subcommand")

    # 1. Scan command
    scan_parser = subparsers.add_parser("scan", help="Scan a directory or full drive and index files.")
    scan_parser.add_argument("path", nargs="?", default=".", help="Directory to scan (default: current directory).")
    scan_parser.add_argument("--min-size", default="50KB", help="Minimum file size to scan (default: 50KB).")
    scan_parser.add_argument("--max-size", default="100MB", help="Maximum file size to scan (default: 100MB).")
    scan_parser.add_argument("--max-video-size", default="4GB", help="Maximum video file size to scan (default: 4GB).")
    scan_parser.add_argument("--no-size-limit", action="store_true", help="Do not enforce min/max size limits.")
    scan_parser.add_argument("-a", "--all-types", action="store_true", help="Scan all supported file types (code, logs, etc.) instead of just major types.")
    scan_parser.add_argument("-t", "--type", choices=["video", "audio", "image", "doc", "text", "code"], help="Scan only specific modality.")
    scan_parser.add_argument("-e", "--ext", help="Comma-separated extensions to scan (e.g. mp4,mp3,jpg).")
    scan_parser.add_argument("-f", "--force", action="store_true", help="Force re-embedding of all files.")
    scan_parser.add_argument("--prune", action="store_true", help="Remove database records for files deleted from disk.")

    # 2. Search command
    search_parser = subparsers.add_parser("search", help="Search indexed files.")
    search_parser.add_argument("query", nargs="+", help="What you are searching for.")
    search_parser.add_argument("-p", "--path", help="Filter search to files under this directory.")
    search_parser.add_argument("-t", "--type", choices=["video", "audio", "image", "doc", "text", "code", "pdf"], help="Filter by file modality.")
    search_parser.add_argument("-e", "--ext", help="Filter by extension(s), e.g. mp3,wav or png.")
    search_parser.add_argument("--min-size", help="Filter by minimum file size (e.g. 100KB, 5MB).")
    search_parser.add_argument("--max-size", help="Filter by maximum file size (e.g. 50MB, 500MB).")
    search_parser.add_argument("--max-video-size", default="4GB", help="Maximum video file size when scanning with --scan (default: 4GB).")
    search_parser.add_argument("--scan", action="store_true", help="Scan target folder before searching.")
    search_parser.add_argument("-a", "--all-types", action="store_true", help="Scan all types if --scan is used.")
    search_parser.add_argument("-k", "--top-k", type=int, default=5, help="Maximum results (default: 5).")
    search_parser.add_argument("--min-score", type=float, default=0.0, help="Minimum score threshold.")
    search_parser.add_argument("-o", "--open", action="store_true", help="Open top match with default Windows app.")
    search_parser.add_argument("-q", "--quiet", action="store_true", help="Output file paths only (for pipelines).")
    search_parser.add_argument("--json", action="store_true", help="Output JSON.")

    # 3. Interactive command
    interactive_parser = subparsers.add_parser("interactive", help="Start continuous interactive search.")
    interactive_parser.add_argument("-p", "--path", help="Filter search to files under this directory.")
    interactive_parser.add_argument("-k", "--top-k", type=int, default=5, help="Maximum results.")

    # 4. Records command
    rec_parser = subparsers.add_parser("records", help="List stored records.")
    rec_parser.add_argument("path", nargs="?", default=None, help="Filter records by directory prefix.")

    # 5. Status command
    subparsers.add_parser("status", help="Show index and daemon status.")

    # 6. Clean command
    clean_parser = subparsers.add_parser("clean", help="Clear index records.")
    clean_parser.add_argument("path", nargs="?", default=None, help="Path prefix to clean (or all if omitted).")

    # 7. Daemon command
    daemon_parser = subparsers.add_parser("daemon", help="Manage background search daemon.")
    daemon_parser.add_argument("action", choices=["start", "stop", "status"], help="Daemon action.")

    subparsers_dict = {
        "scan": scan_parser,
        "search": search_parser,
        "interactive": interactive_parser,
        "records": rec_parser,
        "clean": clean_parser,
        "daemon": daemon_parser,
    }

    if len(sys.argv) == 1:
        interactive_args = argparse.Namespace(db=None, path=None, top_k=5, subcommand="interactive")
        cmd_interactive(interactive_args, subparsers_dict)
        return

    args = parser.parse_args()

    if args.subcommand == "interactive":
        cmd_interactive(args, subparsers_dict)
        return

    if args.subcommand == "scan":
        cmd_scan(args)
        return

    if args.subcommand == "search":
        cmd_search(args.query, args)
        return

    if args.subcommand == "records":
        index = GlobalIndex(db_path=args.db)
        cmd_records(index, getattr(args, "path", None))
        return

    if args.subcommand == "status":
        index = GlobalIndex(db_path=args.db)
        cmd_status(index)
        return

    if args.subcommand == "clean":
        index = GlobalIndex(db_path=args.db)
        cmd_clean(index, getattr(args, "path", None))
        return

    if args.subcommand == "daemon":
        cmd_daemon(args.action)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
