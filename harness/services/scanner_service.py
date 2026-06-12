from pathlib import Path

DEFAULT_IGNORE: frozenset[str] = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".harness", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".eggs", "*.egg-info", "*.pyc", ".DS_Store",
    "coverage", ".coverage", "htmlcov",
})

_KEY_FILES = [
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
    "requirements-dev.txt", "package.json", "go.mod", "Cargo.toml",
    "pom.xml", "build.gradle", "Makefile", "CMakeLists.txt",
    ".python-version", ".nvmrc", ".tool-versions",
]

_MAX_FILE_LINES = 100


def _is_ignored(name: str) -> bool:
    if name in DEFAULT_IGNORE:
        return True
    for pat in DEFAULT_IGNORE:
        if pat.startswith("*") and name.endswith(pat[1:]):
            return True
    return False


def build_file_tree(root: Path, max_depth: int = 4) -> str:
    lines: list[str] = [root.name + "/"]

    def _walk(path: Path, prefix: str, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return
        entries = [e for e in entries if not _is_ignored(e.name)]
        for i, entry in enumerate(entries):
            connector = "└── " if i == len(entries) - 1 else "├── "
            lines.append(prefix + connector + entry.name + ("/" if entry.is_dir() else ""))
            if entry.is_dir():
                extension = "    " if i == len(entries) - 1 else "│   "
                _walk(entry, prefix + extension, depth + 1)

    _walk(root, "", 1)
    return "\n".join(lines)


def read_key_files(root: Path, extra: list[str] | None = None) -> str:
    targets = list(_KEY_FILES) + (extra or [])
    parts: list[str] = []
    for rel in targets:
        path = root / rel
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        snippet = "\n".join(lines[:_MAX_FILE_LINES])
        if len(lines) > _MAX_FILE_LINES:
            snippet += f"\n... ({len(lines) - _MAX_FILE_LINES} more lines)"
        parts.append(f"=== {rel} ===\n{snippet}")
    return "\n\n".join(parts)


def build_codebase_context(harness_dir: Path, extra_files: list[str] | None = None, max_depth: int = 4) -> str:
    root = harness_dir.parent
    tree = build_file_tree(root, max_depth=max_depth)
    key_files = read_key_files(root, extra=extra_files)

    parts: list[str] = []
    if tree:
        parts.append(f"FILE TREE:\n{tree}")
    if key_files:
        parts.append(f"KEY FILES:\n{key_files}")
    return "\n\n".join(parts)
