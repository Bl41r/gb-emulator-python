"""Normalize tracked text files for tidy diffs.

This keeps the repository's text files boring:

* LF line endings
* no trailing spaces/tabs
* exactly one newline at end of non-empty files
"""

from pathlib import Path
import subprocess


BINARY_SUFFIXES = {
    ".bin",
    ".gb",
    ".gbc",
    ".gif",
    ".jpeg",
    ".jpg",
    ".mp3",
    ".png",
    ".prof",
    ".sav",
    ".wav",
    ".zip",
}


def tracked_files():
    """Yield paths tracked by git."""
    result = subprocess.run(
        ["git", "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    )
    for name in result.stdout.splitlines():
        path = Path(name)
        if path.suffix.lower() not in BINARY_SUFFIXES:
            yield path


def normalize(path):
    """Normalize one text file, returning True when it changed."""
    original = path.read_bytes()
    text = original.decode("utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    normalized = "\n".join(line.rstrip(" \t") for line in lines)
    if normalized:
        normalized += "\n"
    data = normalized.encode("utf-8")
    if data != original:
        path.write_bytes(data)
        return True
    return False


def main():
    changed = []
    for path in tracked_files():
        if normalize(path):
            changed.append(str(path))

    for name in changed:
        print(name)
    print(f"normalized {len(changed)} file(s)")


if __name__ == "__main__":
    main()
