import json
import shutil
import subprocess
from pathlib import Path


def is_claude_available() -> bool:
    return shutil.which("claude") is not None


def build_impl_prompt(contract_data: dict, compliance_feedback: str = "") -> str:
    allowed = contract_data.get("allowed_files", [])
    forbidden = contract_data.get("forbidden", [])

    lines = [
        "You are a Syntax Executor. Your ONLY job is to implement exactly what the",
        "approved contract below specifies. You do NOT make architectural decisions.",
        "You do NOT add features not in the contract. You do NOT refactor code outside",
        "the specified files. You do NOT ask questions — just implement.",
        "",
        "═══════════════════════════════════════",
        "APPROVED CONTRACT",
        "═══════════════════════════════════════",
        json.dumps(contract_data, indent=2),
        "",
        "═══════════════════════════════════════",
        "CONSTRAINTS (HARD RULES — NON-NEGOTIABLE)",
        "═══════════════════════════════════════",
        "ALLOWED FILES (only touch these):",
    ]
    for f in allowed:
        lines.append(f"  - {f}")

    if forbidden:
        lines.append("")
        lines.append("FORBIDDEN PATTERNS (never add these):")
        for f in forbidden:
            lines.append(f"  - {f}")

    if compliance_feedback:
        lines += [
            "",
            "═══════════════════════════════════════",
            "PREVIOUS COMPLIANCE FAILURES — FIX THESE",
            "═══════════════════════════════════════",
            compliance_feedback,
            "",
            "The above failures were found in your previous implementation.",
            "Fix ALL of them in this attempt.",
        ]

    lines += [
        "",
        "═══════════════════════════════════════",
        "ACTION",
        "═══════════════════════════════════════",
        "Apply all changes to the files in the current directory now.",
        "Do not output a diff. Write the files directly.",
        "Do not modify any file not listed in ALLOWED FILES.",
    ]

    return "\n".join(lines)


def run_claude_implement(
    prompt: str,
    project_root: Path,
    timeout: int = 300,
) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout + result.stderr
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"Claude Code timed out after {timeout}s"
    except FileNotFoundError:
        return False, "claude CLI not found in PATH"


def capture_diff_staged(project_root: Path, allowed_files: list[str]) -> str:
    existing = [f for f in allowed_files if (project_root / f).exists()]
    if not existing:
        return ""

    subprocess.run(
        ["git", "add"] + existing,
        cwd=project_root,
        check=False,
        capture_output=True,
    )

    result = subprocess.run(
        ["git", "diff", "--cached", "--no-color"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    diff = result.stdout

    subprocess.run(
        ["git", "reset", "HEAD"] + existing,
        cwd=project_root,
        check=False,
        capture_output=True,
    )

    return diff


def reset_allowed_files(project_root: Path, allowed_files: list[str]) -> None:
    for file_path in allowed_files:
        full_path = project_root / file_path
        is_tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", file_path],
            cwd=project_root,
            capture_output=True,
        ).returncode == 0

        if is_tracked:
            subprocess.run(
                ["git", "checkout", "HEAD", "--", file_path],
                cwd=project_root,
                check=False,
                capture_output=True,
            )
        elif full_path.exists():
            full_path.unlink()
