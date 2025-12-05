import fnmatch
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

EXCLUDE_DIRS = {".git", "__pycache__", ".venv"}

USAGE = """\
dumpfiles — copy file contents (with per-file headers) to the system clipboard,
and print a final summary to stderr.

Scenarios:
  1) dumpfiles <folder>              -> copy all files under <folder> (recursive)
  2) dumpfiles <file>                -> copy that single file
  3) dumpfiles "<pattern>"           -> copy files (under .) matching pattern
  4) dumpfiles <folder> "<pattern>"  -> copy files under <folder> matching pattern

Notes:
  - Pattern uses shell-style wildcards (fnmatch), e.g. "*.py", "A*".
  - Excludes common junk dirs: .git, __pycache__, .venv
  - Clipboard content includes a header before each file: "===== <path> ====="
  - Summary (files + lines) prints to stderr; file contents never print to terminal.
Help:
  dumpfiles -h | --help | help
"""


def print_help() -> None:
    print(USAGE)


def is_binary(p: Path) -> bool:
    """Heuristic: treat as binary if first few KB contain NUL bytes."""
    try:
        with p.open("rb") as f:
            return b"\x00" in f.read(4096)
    except Exception:
        # unreadable -> treat as binary to skip
        return True


def walk_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        # prune excluded directories
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for name in filenames:
            yield Path(dirpath) / name


def parse_args(argv: List[str]) -> Tuple[Path, str, bool, Path | None]:
    """
    Returns (root_or_file, pattern, single_file_mode, output_file).
    Supports --output FILE or -o FILE.
    """
    output_file: Path | None = None

    # Handle --output/-o anywhere in args
    cleaned = []
    it = iter(enumerate(argv))
    for i, arg in it:
        if arg in ("--output", "-o"):
            try:
                output_file = Path(argv[i + 1])
            except IndexError:
                print("Error: --output requires a file path.", file=sys.stderr)
                raise SystemExit(2)
            next(it)  # skip the filename
        else:
            cleaned.append(arg)

    argv = cleaned

    if not argv or argv[0] in {"-h", "--help", "help"}:
        print_help()
        raise SystemExit(0)

    first = Path(argv[0])

    if first.is_file():
        return first, "", True, output_file

    if first.is_dir():
        root = first
        pattern = argv[1] if len(argv) >= 2 else "*"
        return root, pattern, False, output_file

    # Treat the first arg as a pattern scoped to "."
    if len(argv) >= 2:
        print(
            "Error: when the first argument is a pattern, do not pass a second argument.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    return Path("."), argv[0], False, output_file


def open_clipboard_proc() -> subprocess.Popen:
    """
    Try to open a process that writes to the system clipboard.

    - macOS: pbcopy
    - Linux (X11): xclip, xsel
    - Linux (Wayland): wl-copy
    """
    commands = [
        ["pbcopy"],  # macOS
        ["xclip", "-selection", "clipboard"],  # Linux X11
        ["xsel", "--clipboard", "--input"],  # Linux X11 alternative
        ["wl-copy"],  # Linux Wayland
    ]

    for cmd in commands:
        try:
            return subprocess.Popen(cmd, stdin=subprocess.PIPE)
        except FileNotFoundError:
            continue

    print(
        "Error: No clipboard tool found. Install one of: pbcopy (macOS), "
        "xclip/xsel (X11), or wl-clipboard (Wayland).",
        file=sys.stderr,
    )
    raise SystemExit(1)


def write_to_clipboard(files: List[Path]) -> int:
    """
    Stream headers + file contents to a clipboard process.
    Returns the number of newline characters found in file contents.
    """
    proc = open_clipboard_proc()
    total_lines = 0

    assert proc.stdin is not None

    for p in files:
        header = f"\n===== {p} =====\n".encode("utf-8", "replace")
        proc.stdin.write(header)
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                proc.stdin.write(chunk)
                total_lines += chunk.count(b"\n")

    proc.stdin.close()
    proc.wait()
    return total_lines


def write_to_file(files: List[Path], output: Path) -> int:
    """Write headers + file contents into a single output file."""
    total_lines = 0

    with output.open("wb") as out:
        for p in files:
            header = f"\n===== {p} =====\n".encode("utf-8", "replace")
            out.write(header)

            with p.open("rb") as f:
                for chunk in iter(lambda: f.read(1 << 16), b""):
                    out.write(chunk)
                    total_lines += chunk.count(b"\n")

    return total_lines


def _run(argv: List[str]) -> int:
    """Internal main, parameterized for testability."""
    target, pattern, single_file_mode, output_file = parse_args(argv)

    files: List[Path] = []

    if single_file_mode:
        if not is_binary(target):
            files.append(target)
    else:
        for p in walk_files(target):
            if fnmatch.fnmatch(p.name, pattern) and not is_binary(p):
                files.append(p)

    if not files:
        print("No matching files.", file=sys.stderr)
        return 1

    # If user requested output to a file → skip clipboard
    if output_file:
        total_lines = write_to_file(files, output_file)
        print(
            f"Wrote {len(files)} files, {total_lines} lines to {output_file}",
            file=sys.stderr,
        )
        return 0

    # Default: write to clipboard
    total_lines = write_to_clipboard(files)
    print(
        f"Copied {len(files)} files, {total_lines} lines to clipboard.",
        file=sys.stderr,
    )
    return 0


def main() -> None:
    """Console script entry point."""
    raise SystemExit(_run(sys.argv[1:]))


if __name__ == "__main__":
    main()
