# Harness — Claude Code Integration as Syntax Executor
## Master Plan (Full Detail)

---

## Why This Exists

Harness's internal Syntax Executor calls a raw LLM to generate a unified diff. This approach is fundamentally broken for real projects:

| Problem | Root Cause |
|---------|-----------|
| Stubs with `// business logic here` | LLM only sees `allowed_files` — no codebase context |
| `action: modify` for non-existent files | No filesystem access |
| DTOs with no getters/setters | No understanding of Java/Spring conventions |
| Manual `git apply` required | Output is synthetic text, not real writes |
| Token limits blow up on large specs | Entire contract + file contents in one prompt |

**Solution:** Delegate the IMPLEMENT step to `claude -p <prompt>` subprocess. Claude Code reads the real project, applies real file writes, understands framework conventions. Harness keeps all governance: decisions, contracts, compliance rules, memory, history.

```
BEFORE:
  Harness LLM → generates diff text → git apply (manual)

AFTER:
  Claude Code subprocess → writes files directly → git diff --cached (Harness captures)
```

The state machine, compliance checker, memory system, and all other Harness logic are **unchanged**. Only the IMPLEMENT step is rewired.

---

## Architecture After Integration

```
harness run "Add REST layer"
        │
        ▼
[INTAKE] run_interrogate()
  → Harness LLM reads codebase context + memories
  → Returns 6–10 structured decisions
        │
        ▼ human answers + approves decisions
        │
[DECISIONS_APPROVED] build_contract()
  → Harness LLM builds contract JSON
  → { scope, allowed_files, forbidden, spec }
        │
        ▼ human approves contract
        │
[CONTRACT_READY] implement()
  ┌─────────────────────────────────────────────┐
  │  if config.use_claude_code and claude in PATH│
  │    build_impl_prompt(contract_data)           │
  │    run_claude_implement(prompt, project_root) │ ← subprocess
  │    capture_diff_staged(project_root, files)   │ ← git add + diff --cached + reset
  │  else                                         │
  │    _prepare_impl_context()                    │
  │    _call_syntax_executor() [old LLM path]     │
  └─────────────────────────────────────────────┘
  → writes diff to .harness/patches/C001.diff
  → task → WAITING_FOR_PATCH_APPROVAL
        │
        ▼ human reviews diff + approves
        │
[IMPLEMENTING] check_compliance()
  → rule_based_check(contract, diff_text)    [no LLM]
  → llm_semantic_check(contract, diff_text)  [LLM]
  → if fail: reset files → reimplement() with feedback
        │
        ▼
[VALIDATING] run validate_commands
        │
        ▼
[DONE] write_memory()
```

---

## How the Diff is Captured (Key Mechanism)

```
1. Claude Code writes files to disk (real files, real content)
2. capture_diff_staged(project_root, allowed_files):
     a. git add <allowed_files_that_exist_on_disk>
     b. git diff --cached --no-color           ← proper +++ b/relative/path headers
     c. git reset HEAD <same_files>            ← unstage, keep working tree changes
     d. return diff string
3. diff_text saved to .harness/patches/C001.diff
4. compliance checker reads diff_text (unchanged API)
```

Why staging works:
- `git diff --cached` always produces `+++ b/relative/path` — no absolute path issues
- Works for both NEW files (untracked → staged as new) and MODIFIED files
- Unstage with `git reset HEAD` restores index without touching working tree
- User's written files remain on disk; only git staging is temporarily touched

---

## How Reimplement Works on Compliance Failure

```
compliance fails
    │
    ▼
reset_allowed_files(project_root, allowed_files):
    for each file in allowed_files:
        is_tracked = (git ls-files --error-unmatch <file>).returncode == 0
        if is_tracked:
            git checkout HEAD -- <file>    ← restore to HEAD
        elif file.exists():
            file.unlink()                  ← delete new file created by Claude Code
    │
    ▼
build_impl_prompt(contract_data, compliance_feedback=report.summary)
    │
    ▼
run_claude_implement(prompt, project_root)   ← Claude Code tries again
    │
    ▼
capture_diff_staged(project_root, allowed_files)
    │
    ▼
new diff → new patch record → compliance check again
```

---

## Build Checklist (for /loop)

**Paste this into Claude Code to run autonomously:**

```
/loop Implement Phase 15 — Claude Code Syntax Executor Integration in Harness.

PLAN FILE: plans/phase15_claude_code_integration.md
CHECKLIST SECTION: "Build Checklist" (the - [ ] items below)

For each unchecked [ ] item:
1. Read the corresponding Phase section in plans/phase15_claude_code_integration.md for exact specs
2. Implement exactly what the spec says — no more, no less
3. Run the Phase Gate command from the plan — it MUST pass green before continuing
4. Mark the item [x] in plans/phase15_claude_code_integration.md
5. Also mark the matching item [x] in CLAUDE.md under "Phase 15"
6. Run pytest tests/ -q — must be green after every phase
7. Move to the next unchecked item

Rules:
- Never skip a Gate
- Never commit without pytest passing
- Never implement beyond what the phase spec says
- If a Gate fails, fix it before moving on
- After all 9 items are checked, print "Phase 15 COMPLETE"
```

- [x] Phase 1 — `config.py`: `use_claude_code`, `claude_code_timeout`
- [x] Phase 2 — `harness/services/claude_executor.py` (new file, 5 functions)
- [x] Phase 3 — `implementation_service.py`: dispatch + reimplement update
- [x] Phase 4 — `runtime.py`: pass `config=` to implement/reimplement
- [x] Phase 5 — `cli.py`: config-set, implement display, apply display
- [x] Phase 6 — `server.py`: pass `config` to `harness_implement` tool
- [x] Phase 7 — `app.py`: Claude Code mode badge, apply button, config toggles
- [x] Phase 8 — `tests/test_claude_executor.py` (13 test cases)
- [x] Phase 9 — `CLAUDE.md`: Phase 15 entry + mark complete

---

## Phase 1 — Config Fields

### Goal
Add `use_claude_code` (bool, default True) and `claude_code_timeout` (int seconds, default 300) to `HarnessConfig`. Wire into `cli.py` config-set so users can change them at runtime.

### File: `harness/config.py`

**Current state of `HarnessConfig`:**
```python
class HarnessConfig(BaseModel):
    project_name: str
    llm_provider: str
    llm_model: str
    validate_commands: list[str] = []
    max_tokens: Annotated[int, Field(ge=1)] = 4096
    llm_retries: Annotated[int, Field(ge=1)] = 3
    context_max_depth: Annotated[int, Field(ge=1)] = 4
    context_extra_files: list[str] = []
```

**Add after `context_extra_files`:**
```python
    use_claude_code: bool = True
    claude_code_timeout: Annotated[int, Field(ge=10)] = 300
```

- `use_claude_code = True` — opt-in by default since `claude` CLI is present
- `claude_code_timeout = 300` — 5 minutes; enough for complex files, avoids hanging forever
- `Field(ge=10)` — floor at 10s; anything less means the subprocess can't even start

**No migration needed** — `HarnessConfig` uses `model_validate` which applies defaults for missing keys. Existing `config.json` files that lack these fields will get defaults automatically.

### File: `harness/cli.py` — `config_set` command

**Current `_INT_FIELDS` set (approx line 60):**
```python
_INT_FIELDS = {"max_tokens", "llm_retries", "context_max_depth"}
```

**Change:**
```python
_INT_FIELDS = {"max_tokens", "llm_retries", "context_max_depth", "claude_code_timeout"}
```

**Current `config_set()` function logic (approx line 730):**
```python
@config_app.command("set")
def config_set(key: str, value: str) -> None:
    harness_dir, config, db = _get_ctx()
    data = json.loads((harness_dir / "config.json").read_text())
    if key in _INT_FIELDS:
        typed = int(value)
    elif key == "context_extra_files":
        typed = json.loads(value)
    else:
        typed = value
    data[key] = typed
    ...
```

**Add a new elif branch for boolean fields, BEFORE the final else:**
```python
    elif key == "use_claude_code":
        if value.lower() not in ("true", "false", "1", "0", "yes", "no"):
            _abort(f"Invalid boolean value: {value!r}. Use true/false.")
        typed: bool = value.lower() in ("true", "1", "yes")
```

**Full updated config_set logic block:**
```python
    if key in _INT_FIELDS:
        try:
            typed = int(value)
        except ValueError:
            _abort(f"{key} must be an integer, got {value!r}")
    elif key == "use_claude_code":
        if value.lower() not in ("true", "false", "1", "0", "yes", "no"):
            _abort(f"Invalid boolean: {value!r}. Use true or false.")
        typed = value.lower() in ("true", "1", "yes")
    elif key == "context_extra_files":
        typed = json.loads(value)
    else:
        typed = value
    data[key] = typed
    (harness_dir / "config.json").write_text(json.dumps(data, indent=2))
    console.print(f"[green]config.{key} = {typed!r}[/green]")
```

### Phase 1 Gate
```bash
python -c "
from harness.config import HarnessConfig
c = HarnessConfig(project_name='x', llm_provider='anthropic', llm_model='m')
assert c.use_claude_code == True, 'use_claude_code default wrong'
assert c.claude_code_timeout == 300, 'claude_code_timeout default wrong'
c2 = HarnessConfig(project_name='x', llm_provider='anthropic', llm_model='m',
                   use_claude_code=False, claude_code_timeout=60)
assert c2.use_claude_code == False
assert c2.claude_code_timeout == 60
print('Phase 1 PASS')
"
pytest tests/ -q
```

---

## Phase 2 — `harness/services/claude_executor.py`

### Goal
A standalone service module with exactly 5 functions. No imports from `cli.py`. No typer. Pure Python + stdlib subprocess.

### File to create: `harness/services/claude_executor.py`

#### Imports
```python
import json
import shutil
import subprocess
from pathlib import Path
```

---

#### Function 1: `is_claude_available() -> bool`

**Purpose:** Check at runtime whether the `claude` CLI is reachable in PATH. Called in `implement()` to decide dispatch path.

**Implementation:**
```python
def is_claude_available() -> bool:
    return shutil.which("claude") is not None
```

**Why `shutil.which` not `subprocess.run(["which", "claude"])`:**
- `shutil.which` is pure Python, works on all platforms, no subprocess overhead
- Returns the full path string if found, `None` if not — single boolean expression

**Edge cases:**
- `claude` installed but not executable: `shutil.which` returns `None` (permission checked)
- `claude` aliased in shell but not in PATH: returns `None` (subprocess env ≠ shell env)
- Result is not cached — called once per `implement()` invocation (cheap enough)

---

#### Function 2: `build_impl_prompt(contract_data: dict, compliance_feedback: str = "") -> str`

**Purpose:** Build the full text prompt to send to Claude Code via `-p`. The prompt must:
1. Declare Claude Code's role as a pure Syntax Executor (no decisions)
2. Provide the full contract JSON so Claude Code knows exactly what to do
3. List allowed files explicitly (redundant with contract but makes the constraint clearer)
4. List forbidden patterns
5. If compliance failed: include the failure summary so Claude Code fixes those issues
6. Close with an action instruction

**Full implementation:**
```python
def build_impl_prompt(contract_data: dict, compliance_feedback: str = "") -> str:
    allowed = contract_data.get("allowed_files", [])
    forbidden = contract_data.get("forbidden", [])
    spec = contract_data.get("spec", {})

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
        f"ALLOWED FILES (only touch these):",
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
```

**Design decisions:**
- ASCII separators (`═══`) make sections visually clear in Claude Code's context window
- Redundancy (allowed_files in both contract JSON and explicit list) is intentional — reinforces the constraint
- `compliance_feedback` section only appears on retry — keeps first-attempt prompt shorter
- No file content injected — Claude Code reads them itself from the working directory

---

#### Function 3: `run_claude_implement(prompt: str, project_root: Path, timeout: int = 300) -> tuple[bool, str]`

**Purpose:** Spawn `claude -p <prompt>` as a subprocess in `project_root`. Return `(success, output)`.

**Implementation:**
```python
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
```

**Why `capture_output=True`:**
- Prevents Claude Code's interactive UI from polluting the terminal
- stdout + stderr both captured — Claude Code may log warnings to stderr
- The Streamlit UI / CLI can then display `output` as a progress log

**Why `cwd=project_root`:**
- Claude Code resolves relative paths from `cwd`
- If cwd is the project root, Claude Code can read and write `src/main/java/...` directly
- Do NOT use `harness_dir` as cwd — that's `.harness/` inside the project

**Timeout behavior:**
- `subprocess.TimeoutExpired` is raised by `subprocess.run` when the process runs too long
- We catch it and return `(False, "timed out")` — caller raises `LLMOutputError`
- Claude Code is killed automatically when the exception is raised

**`FileNotFoundError`:**
- Raised when `claude` is not in PATH at subprocess creation time
- Should not happen in practice (we check `is_claude_available()` first) but defense matters

**Return value contract:**
- `(True, output)` — Claude Code exited 0, files were written
- `(False, output)` — Claude Code exited non-zero, or timed out, or not found
- Caller is responsible for raising `LLMOutputError` on `False`

---

#### Function 4: `capture_diff_staged(project_root: Path, allowed_files: list[str]) -> str`

**Purpose:** After Claude Code writes files, produce a unified diff of all changes. The staging trick ensures proper relative paths in headers.

**Implementation:**
```python
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
```

**Step-by-step logic:**
1. Filter `allowed_files` to only those that exist on disk (`project_root / f`). Claude Code may not create all files if some spec items weren't relevant.
2. `git add <existing_files>` — stages all changes (new files appear as "new file mode", modified files as changes)
3. `git diff --cached --no-color` — shows what's staged. Output has proper `+++ b/relative/path` headers because git uses repo-relative paths in cached diffs
4. `git reset HEAD <files>` — unstages everything. Working tree is unchanged. User's written files remain.
5. Return `diff` string

**Why `--no-color`:**
- ANSI escape codes in the diff would confuse `st.code(..., language="diff")` in Streamlit
- The compliance checker regex also doesn't handle ANSI

**Error handling:**
- `git add` failure (`check=False`) — if the project has no git repo, this silently fails. `git diff --cached` then returns empty string. Caller detects empty diff and raises error.
- `git reset HEAD` failure — non-fatal. Files remain staged, which is unusual but not catastrophic. The user can run `git reset` manually.

**Empty diff scenario:**
- Claude Code ran but wrote no files → `existing = []` → returns `""`
- Caller raises `LLMOutputError("Claude Code ran but produced no changes")`

---

#### Function 5: `reset_allowed_files(project_root: Path, allowed_files: list[str]) -> None`

**Purpose:** Before reimplementing after compliance failure, undo all changes Claude Code made. Restores the project to a clean state.

**Implementation:**
```python
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
```

**Decision tree per file:**
```
file_path in allowed_files
    │
    ├─ git ls-files --error-unmatch <file>  →  returncode 0  (tracked)
    │       → git checkout HEAD -- <file>   (restore to HEAD content)
    │
    └─ git ls-files --error-unmatch <file>  →  returncode 1  (not tracked)
            → if file.exists(): file.unlink()  (delete new file Claude Code created)
            → if not exists: nothing to do
```

**Why `git checkout HEAD -- <file>` not `git checkout -- <file>`:**
- `git checkout -- <file>` restores from index (staged state), which might itself be a modified version
- `git checkout HEAD -- <file>` unconditionally restores from HEAD commit — guaranteed clean

**Files NOT in allowed_files:**
- Claude Code is instructed not to touch them, but if it did anyway, we don't reset them here
- The compliance checker's rule-based check (`scope_violation`) will catch this and block approval

### Phase 2 Gate
```bash
python -c "
from harness.services.claude_executor import (
    is_claude_available,
    build_impl_prompt,
    run_claude_implement,
    capture_diff_staged,
    reset_allowed_files,
)
print('all imports OK')
print('claude available:', is_claude_available())

# Verify prompt structure
contract = {'id': 'C001', 'scope': 'test', 'allowed_files': ['foo.py'],
            'forbidden': ['import os'], 'spec': {}}
prompt = build_impl_prompt(contract)
assert 'foo.py' in prompt
assert 'import os' in prompt
assert 'APPROVED CONTRACT' in prompt
prompt_retry = build_impl_prompt(contract, compliance_feedback='Missing method X')
assert 'PREVIOUS COMPLIANCE FAILURES' in prompt_retry
assert 'Missing method X' in prompt_retry
print('build_impl_prompt OK')
print('Phase 2 PASS')
"
```

---

## Phase 3 — Update `implementation_service.py`

### Goal
Add a `config` parameter to `implement()` and `reimplement()`. When `config.use_claude_code=True` and `claude` is in PATH, use the Claude Code path. Otherwise fall through to the existing LLM path (unchanged).

### File: `harness/services/implementation_service.py`

#### New imports to add at the top
```python
from harness.services.claude_executor import (
    is_claude_available,
    build_impl_prompt,
    run_claude_implement,
    capture_diff_staged,
    reset_allowed_files,
)
```

---

#### Updated `implement()` signature
```python
def implement(
    task: dict,
    contract: dict,
    harness_dir: Path,
    llm: LLMAdapter,
    db: Database,
    config=None,          # NEW — HarnessConfig | None
) -> dict:
```

**Why `config=None` not `config: HarnessConfig`:**
- `HarnessConfig` would create a circular import risk if config.py imports services
- `None` default means all existing callers (`app.py`, `server.py`, tests) that don't pass config still work, falling through to LLM path
- `getattr(config, "use_claude_code", False)` safely handles `None`

#### Full updated `implement()` logic
```python
def implement(task, contract, harness_dir, llm, db, config=None) -> dict:
    assert_command_allowed("implement", TaskStatus(task["status"]))
    project_root = harness_dir.parent

    # Decide which path to use
    use_cc = (
        config is not None
        and getattr(config, "use_claude_code", False)
        and is_claude_available()
    )

    if use_cc:
        # ── Claude Code path ──────────────────────────────────────
        allowed_files = json.loads(contract["allowed_files_json"])
        contract_data = {
            "id": contract["id"],
            "scope": contract["scope"],
            "allowed_files": allowed_files,
            "forbidden": json.loads(contract["forbidden_json"]),
            "spec": json.loads(contract["spec_json"]),
        }
        prompt = build_impl_prompt(contract_data)
        timeout = getattr(config, "claude_code_timeout", 300)

        success, output = run_claude_implement(prompt, project_root, timeout)
        if not success:
            raise LLMOutputError(f"Claude Code failed:\n{output[:2000]}")

        diff_text = capture_diff_staged(project_root, allowed_files)
        if not diff_text.strip():
            raise LLMOutputError(
                "Claude Code ran successfully but produced no file changes. "
                f"Claude output:\n{output[:1000]}"
            )
    else:
        # ── LLM fallback path (unchanged) ─────────────────────────
        file_contents, contract_data = _prepare_impl_context(contract, project_root)
        diff_text = _call_syntax_executor(contract_data, file_contents, llm)

    # ── Common path: save patch, update DB, transition state ──────
    patches_dir = harness_dir / "patches"
    patches_dir.mkdir(exist_ok=True)
    patch_file = patches_dir / f"{contract['id']}.diff"
    patch_file.write_text(diff_text)

    patch_id = db.new_patch_id()
    db.create_patch({
        "id": patch_id,
        "contract_id": contract["id"],
        "diff_text": diff_text,
        "status": "generated",
        "created_at": now_iso(),
    })

    transition(task, TaskStatus.WAITING_FOR_PATCH_APPROVAL, db)

    return {
        "patch_id": patch_id,
        "patch_file": str(patch_file),
        "lines": diff_text.count("\n"),
        "mode": "claude_code" if use_cc else "llm",  # NEW — for display
    }
```

**Key detail: `mode` field in return dict:**
- `"mode": "claude_code"` or `"mode": "llm"` — tells CLI/UI which path was used
- CLI displays `[cyan]Claude Code[/cyan]` or `[yellow]LLM Syntax Executor[/yellow]`
- No downstream code depends on this field — safe to add

---

#### Updated `reimplement()` signature and logic
```python
def reimplement(
    task: dict,
    contract: dict,
    harness_dir: Path,
    llm: LLMAdapter,
    db: Database,
    compliance_summary: str = "",
    config=None,          # NEW
) -> dict:
    assert_command_allowed("reimplement", TaskStatus(task["status"]))
    project_root = harness_dir.parent

    use_cc = (
        config is not None
        and getattr(config, "use_claude_code", False)
        and is_claude_available()
    )

    if use_cc:
        allowed_files = json.loads(contract["allowed_files_json"])
        contract_data = {
            "id": contract["id"],
            "scope": contract["scope"],
            "allowed_files": allowed_files,
            "forbidden": json.loads(contract["forbidden_json"]),
            "spec": json.loads(contract["spec_json"]),
        }

        # Reset files from previous failed attempt BEFORE trying again
        reset_allowed_files(project_root, allowed_files)

        prompt = build_impl_prompt(contract_data, compliance_feedback=compliance_summary)
        timeout = getattr(config, "claude_code_timeout", 300)

        success, output = run_claude_implement(prompt, project_root, timeout)
        if not success:
            raise LLMOutputError(f"Claude Code failed on reimplement:\n{output[:2000]}")

        diff_text = capture_diff_staged(project_root, allowed_files)
        if not diff_text.strip():
            raise LLMOutputError("Claude Code produced no changes on reimplement")
    else:
        # LLM fallback — compliance feedback injected into contract_data
        file_contents, contract_data = _prepare_impl_context(contract, project_root)
        if compliance_summary:
            contract_data["compliance_feedback"] = compliance_summary
        diff_text = _call_syntax_executor(contract_data, file_contents, llm)

    # Save new patch
    patches_dir = harness_dir / "patches"
    patches_dir.mkdir(exist_ok=True)
    patch_file = patches_dir / f"{contract['id']}.diff"
    patch_file.write_text(diff_text)

    patch_id = db.new_patch_id()
    db.create_patch({
        "id": patch_id,
        "contract_id": contract["id"],
        "diff_text": diff_text,
        "status": "generated",
        "created_at": now_iso(),
    })

    return {
        "patch_id": patch_id,
        "patch_file": str(patch_file),
        "lines": diff_text.count("\n"),
        "mode": "claude_code" if use_cc else "llm",
    }
```

**Critical: `reset_allowed_files` is called BEFORE `run_claude_implement` in `reimplement()`:**
- Without reset, Claude Code sees the broken files from the first attempt and might repeat the same mistakes
- With reset, it starts from a clean HEAD state and sees the compliance feedback as its only guide

### Phase 3 Gate
```bash
python -c "
from harness.services.implementation_service import implement, reimplement, approve_patch, reject_patch
import inspect
sig = inspect.signature(implement)
assert 'config' in sig.parameters, 'config param missing from implement'
sig2 = inspect.signature(reimplement)
assert 'config' in sig2.parameters, 'config param missing from reimplement'
print('Phase 3 PASS')
"
pytest tests/ -q
```

---

## Phase 4 — Update `runtime.py`

### Goal
Thread `config` through to `implement()` and `reimplement()` calls inside `run_until_pause()`. No logic changes to the state machine — only parameter passing.

### File: `harness/runtime.py`

`run_until_pause()` already receives `config: HarnessConfig` as a parameter. It passes it to `run_interrogate()` and `build_contract()` already. The two missing call sites are in the `CONTRACT_READY` and `IMPLEMENTING` branches.

#### Locate the CONTRACT_READY branch (approx line 140–165)

**Current code:**
```python
elif status == TaskStatus.CONTRACT_READY:
    contract = db.get_latest_contract(task["id"])
    if not contract:
        return RuntimeResult(... paused_at=PauseReason.ERROR ...)
    result = implement(task, contract, harness_dir, llm, db)
    contract_id = contract["id"]
    patch_file = result["patch_file"]
```

**Change** (add `config=config`):
```python
    result = implement(task, contract, harness_dir, llm, db, config=config)
```

#### Locate the IMPLEMENTING branch compliance retry (approx line 175–210)

**Current code:**
```python
elif status == TaskStatus.IMPLEMENTING:
    ...
    if not report.passed and compliance_retries < max_compliance_retries:
        compliance_retries += 1
        reimplement(task, contract, harness_dir, llm, db,
                    compliance_summary=report.summary)
```

**Change** (add `config=config`):
```python
        reimplement(task, contract, harness_dir, llm, db,
                    compliance_summary=report.summary, config=config)
```

**That is all.** No other changes to `runtime.py`. The `config` object is already available in scope — it's a parameter of `run_until_pause()`.

### Phase 4 Gate
```bash
python -c "from harness.runtime import run_until_pause, PauseReason, RuntimeResult; print('Phase 4 PASS')"
pytest tests/ -q
```

---

## Phase 5 — Update `cli.py`

### Goal
Three targeted changes: (1) config-set handles new fields, (2) `implement` command shows mode and passes config, (3) `apply` command explains what happened based on mode.

### File: `harness/cli.py`

#### Change A: `_INT_FIELDS` set

Locate the `_INT_FIELDS` definition (approx line 60):
```python
_INT_FIELDS = {"max_tokens", "llm_retries", "context_max_depth"}
```

Change to:
```python
_INT_FIELDS = {"max_tokens", "llm_retries", "context_max_depth", "claude_code_timeout"}
```

#### Change B: `config_set()` boolean handling

Locate the if/elif chain inside `config_set()` that currently looks like:
```python
if key in _INT_FIELDS:
    typed = int(value)
elif key == "context_extra_files":
    typed = json.loads(value)
else:
    typed = value
```

Insert the `use_claude_code` branch between `_INT_FIELDS` and `context_extra_files`:
```python
if key in _INT_FIELDS:
    try:
        typed = int(value)
    except ValueError:
        _abort(f"{key} requires an integer value, got: {value!r}")
elif key == "use_claude_code":
    if value.lower() not in ("true", "false", "1", "0", "yes", "no"):
        _abort(f"use_claude_code requires true or false, got: {value!r}")
    typed = value.lower() in ("true", "1", "yes")
elif key == "context_extra_files":
    typed = json.loads(value)
else:
    typed = value
```

#### Change C: `implement` command — show mode, pass config

Locate the `implement` command function. Its current end:
```python
    result = impl_implement(task, contract, harness_dir, llm, db)
    console.print(f"[green]Patch written:[/green] {result['patch_file']}")
    console.print(f"Lines: {result['lines']}")
```

**Add the mode display BEFORE calling implement, and pass config:**
```python
    # Show which executor will be used
    from harness.services.claude_executor import is_claude_available
    if config.use_claude_code and is_claude_available():
        console.print("[cyan]Syntax Executor: Claude Code CLI[/cyan]")
    else:
        if config.use_claude_code and not is_claude_available():
            console.print("[yellow]Claude Code not found in PATH — falling back to LLM[/yellow]")
        else:
            console.print("[yellow]Syntax Executor: LLM (claude_code disabled)[/yellow]")

    result = impl_implement(task, contract, harness_dir, llm, db, config=config)

    mode_label = "Claude Code" if result.get("mode") == "claude_code" else "LLM"
    console.print(f"[green]Patch generated via {mode_label}[/green]")
    console.print(f"  File: {result['patch_file']}")
    console.print(f"  Lines: {result['lines']}")
    console.print("\nRun [bold]harness apply[/bold] to approve and proceed to compliance check.")
```

#### Change D: `apply` command — context-aware message

The `apply` command currently calls `approve_patch()` and shows a generic message. Add mode-aware messaging:

```python
@app.command()
def apply() -> None:
    """Approve the patch and advance to compliance check."""
    harness_dir, config, db = _get_ctx()
    task = _get_active_task_or_exit(db)
    ...
    approve_patch(task, db)

    from harness.services.claude_executor import is_claude_available
    if config.use_claude_code and is_claude_available():
        console.print("[green]Patch approved.[/green]")
        console.print("Files are already written to disk by Claude Code.")
        console.print("Running compliance check next...")
    else:
        patch = db.get_latest_patch(contract["id"])
        patch_path = harness_dir / "patches" / f"{contract['id']}.diff"
        console.print("[green]Patch approved.[/green]")
        console.print(f"[yellow]Apply the patch manually:[/yellow]")
        console.print(f"  git apply {patch_path}")
        console.print("Then run [bold]harness check[/bold].")
```

### Phase 5 Gate
```bash
# Config set works
cd /tmp && harness init --provider anthropic --model claude-sonnet-4-6 2>/dev/null || true
harness config set use_claude_code false
harness config set use_claude_code true
harness config set claude_code_timeout 120

# Help shows commands
harness implement --help
harness apply --help

pytest tests/ -q
```

---

## Phase 6 — Update `server.py`

### Goal
Pass `config` to `implement()` in the `harness_implement` MCP tool. One-line change.

### File: `harness/server.py`

#### Locate `harness_implement` tool (approx line 240–270)

**Current:**
```python
@mcp.tool()
async def harness_implement(contract_id: str) -> dict:
    """Generate implementation patch from approved contract."""
    harness_dir, config, db = _ctx()
    llm = _get_llm()
    task = _active_task()
    if not task:
        return {"error": "No active task"}
    contract = db.get_contract(contract_id)
    if not contract:
        return {"error": f"Contract {contract_id} not found"}
    result = implement(task, contract, harness_dir, llm, db)
    return result
```

**Change** (add `config=config`):
```python
    result = implement(task, contract, harness_dir, llm, db, config=config)
```

No other changes to `server.py`. The MCP server's `_ctx()` already returns `config`.

### Phase 6 Gate
```bash
python -c "from harness.server import run; print('Phase 6 PASS')"
pytest tests/ -q
```

---

## Phase 7 — Update `app.py` (Streamlit)

### Goal
Three UI changes: (1) mode badge on Patch page, (2) Apply button label and message based on mode, (3) new config toggles for `use_claude_code` and `claude_code_timeout`.

### File: `harness/app.py`

#### Change A: Mode badge on Patch page

At the top of the "🩹 Patch" page section, after loading config:
```python
from harness.services.claude_executor import is_claude_available

# Show current executor mode
if config.use_claude_code and is_claude_available():
    st.success("⚡ Claude Code mode — files will be written directly to disk")
elif config.use_claude_code and not is_claude_available():
    st.warning("⚠️ use_claude_code=True but `claude` CLI not found in PATH — using LLM fallback")
else:
    st.info("🤖 LLM Syntax Executor mode — generates a .diff file for manual git apply")
```

Place this ABOVE the "Generate Patch" button.

#### Change B: Generate Patch button — pass config

**Current:**
```python
if st.button("Generate Patch"):
    with st.spinner("Generating patch..."):
        result = implement(task, c, harness_dir, llm, db)
```

**Change:**
```python
if st.button("Generate Patch"):
    spinner_msg = "Claude Code is implementing..." if (config.use_claude_code and is_claude_available()) else "LLM generating diff..."
    with st.spinner(spinner_msg):
        result = implement(task, c, harness_dir, llm, db, config=config)
```

#### Change C: Apply/Approve button — mode-aware

In the patch display section where the approve button is shown:

**Current:**
```python
if st.button("✅ Approve Patch"):
    approve_patch(task, db)
    st.success("Patch approved — run compliance check next")
```

**Change:**
```python
if config.use_claude_code and is_claude_available():
    button_label = "✅ Approve (files already on disk)"
    help_text = "Files were written directly by Claude Code. Approving starts compliance check."
else:
    button_label = "✅ Approve Patch"
    help_text = f"Remember to run: git apply .harness/patches/{c['id']}.diff"

if st.button(button_label, help=help_text):
    approve_patch(task, db)
    if config.use_claude_code and is_claude_available():
        st.success("Approved. Compliance check will verify the written files.")
    else:
        st.warning(f"Approved. Apply the patch: `git apply .harness/patches/{c['id']}.diff`")
    st.rerun()
```

#### Change D: Config page — new toggles

In the config expander (typically in sidebar or Settings page), add:

```python
st.subheader("Syntax Executor")

use_cc = st.toggle(
    "Use Claude Code CLI as Syntax Executor",
    value=config.use_claude_code,
    help="When enabled, uses `claude -p` to write files directly. Falls back to LLM if `claude` not in PATH."
)

cc_timeout = st.number_input(
    "Claude Code Timeout (seconds)",
    min_value=10,
    max_value=1800,
    value=config.claude_code_timeout,
    step=30,
    help="How long to wait for Claude Code to finish implementing before timing out."
)

if st.button("Save Executor Config"):
    data = json.loads((harness_dir / "config.json").read_text())
    data["use_claude_code"] = use_cc
    data["claude_code_timeout"] = cc_timeout
    (harness_dir / "config.json").write_text(json.dumps(data, indent=2))
    st.success("Saved")
    st.rerun()
```

### Phase 7 Gate
```bash
python -c "from harness.app import main; print('Phase 7 import PASS')"
pytest tests/ -q
# Manual: streamlit run harness/app.py → navigate to Patch page → verify mode badge
```

---

## Phase 8 — `tests/test_claude_executor.py`

### Goal
13 unit tests covering all 5 functions. All tests use `unittest.mock` — no real `claude` subprocess, no real git calls.

### File to create: `tests/test_claude_executor.py`

#### Imports
```python
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest
from harness.services.claude_executor import (
    is_claude_available,
    build_impl_prompt,
    run_claude_implement,
    capture_diff_staged,
    reset_allowed_files,
)
```

---

#### `TestIsClaudeAvailable` (2 tests)

```python
class TestIsClaudeAvailable:
    def test_returns_true_when_claude_in_path(self):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            assert is_claude_available() is True

    def test_returns_false_when_not_in_path(self):
        with patch("shutil.which", return_value=None):
            assert is_claude_available() is False
```

---

#### `TestBuildImplPrompt` (4 tests)

```python
class TestBuildImplPrompt:
    CONTRACT = {
        "id": "C001",
        "scope": "Add REST endpoints",
        "allowed_files": ["src/Controller.java", "src/Service.java"],
        "forbidden": ["System.out.println", "TODO"],
        "spec": {"files": [{"path": "src/Controller.java", "action": "create"}]},
    }

    def test_contains_contract_id(self):
        prompt = build_impl_prompt(self.CONTRACT)
        assert "C001" in prompt

    def test_contains_all_allowed_files(self):
        prompt = build_impl_prompt(self.CONTRACT)
        assert "src/Controller.java" in prompt
        assert "src/Service.java" in prompt

    def test_contains_forbidden_patterns(self):
        prompt = build_impl_prompt(self.CONTRACT)
        assert "System.out.println" in prompt
        assert "TODO" in prompt

    def test_compliance_feedback_section_present_when_provided(self):
        prompt = build_impl_prompt(self.CONTRACT, compliance_feedback="Missing method X")
        assert "PREVIOUS COMPLIANCE FAILURES" in prompt
        assert "Missing method X" in prompt

    def test_no_compliance_section_when_empty(self):
        prompt = build_impl_prompt(self.CONTRACT, compliance_feedback="")
        assert "PREVIOUS COMPLIANCE FAILURES" not in prompt
```

---

#### `TestRunClaudeImplement` (3 tests)

```python
class TestRunClaudeImplement:
    def test_returns_true_on_zero_exit(self, tmp_path):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Done."
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            success, output = run_claude_implement("prompt", tmp_path, timeout=60)
        assert success is True
        assert "Done." in output
        mock_run.assert_called_once_with(
            ["claude", "-p", "prompt"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_returns_false_on_nonzero_exit(self, tmp_path):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error: file not found"
        with patch("subprocess.run", return_value=mock_result):
            success, output = run_claude_implement("prompt", tmp_path)
        assert success is False
        assert "Error: file not found" in output

    def test_returns_false_on_timeout(self, tmp_path):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 300)):
            success, output = run_claude_implement("prompt", tmp_path, timeout=300)
        assert success is False
        assert "timed out" in output.lower()
```

---

#### `TestCaptureDiffStaged` (2 tests)

```python
class TestCaptureDiffStaged:
    def test_returns_diff_for_existing_files(self, tmp_path):
        # Create fake files so the existence check passes
        (tmp_path / "foo.py").write_text("x = 1")
        
        add_result = MagicMock(returncode=0)
        diff_result = MagicMock(returncode=0, stdout="diff --git a/foo.py b/foo.py\n+x = 1\n")
        reset_result = MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=[add_result, diff_result, reset_result]) as mock_run:
            diff = capture_diff_staged(tmp_path, ["foo.py"])

        assert "foo.py" in diff
        # Verify the three git calls were made in order
        calls = mock_run.call_args_list
        assert calls[0][0][0][:2] == ["git", "add"]
        assert calls[1][0][0][:3] == ["git", "diff", "--cached"]
        assert calls[2][0][0][:3] == ["git", "reset", "HEAD"]

    def test_returns_empty_when_no_files_exist(self, tmp_path):
        # No files exist on disk → existing list is empty → no git calls
        with patch("subprocess.run") as mock_run:
            diff = capture_diff_staged(tmp_path, ["nonexistent.py"])
        assert diff == ""
        mock_run.assert_not_called()
```

---

#### `TestResetAllowedFiles` (2 tests)

```python
class TestResetAllowedFiles:
    def test_restores_tracked_file(self, tmp_path):
        (tmp_path / "tracked.java").write_text("old content")
        
        ls_result = MagicMock(returncode=0)   # file is tracked
        checkout_result = MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=[ls_result, checkout_result]) as mock_run:
            reset_allowed_files(tmp_path, ["tracked.java"])

        # Second call must be git checkout HEAD
        checkout_call = mock_run.call_args_list[1]
        assert "checkout" in checkout_call[0][0]
        assert "tracked.java" in checkout_call[0][0]

    def test_deletes_new_untracked_file(self, tmp_path):
        new_file = tmp_path / "NewController.java"
        new_file.write_text("new content")
        
        ls_result = MagicMock(returncode=1)   # not tracked

        with patch("subprocess.run", return_value=ls_result):
            reset_allowed_files(tmp_path, ["NewController.java"])

        assert not new_file.exists()   # file was deleted
```

---

### Phase 8 Gate
```bash
pytest tests/test_claude_executor.py -v
# Expected: 13 passed

pytest tests/ -q
# Expected: all previous tests still pass
```

---

## Phase 9 — CLAUDE.md Update

### Goal
Add Phase 15 to the Build Progress section. Mark all 9 items checked when they are done.

### File: `CLAUDE.md`

**Find the "## Build Progress" section and append after Phase 13/14:**

```markdown
### Phase 15 — Claude Code Syntax Executor Integration

- [ ] harness/config.py: `use_claude_code: bool = True`, `claude_code_timeout: int = 300`
- [ ] harness/services/claude_executor.py: 5 functions (is_claude_available, build_impl_prompt, run_claude_implement, capture_diff_staged, reset_allowed_files)
- [ ] harness/services/implementation_service.py: implement() + reimplement() dispatch to Claude Code or LLM
- [ ] harness/runtime.py: pass `config=config` to implement() and reimplement()
- [ ] harness/cli.py: config-set handles use_claude_code/claude_code_timeout, implement shows mode, apply shows mode-aware message
- [ ] harness/server.py: harness_implement tool passes config=config
- [ ] harness/app.py: mode badge, mode-aware apply button, config toggles
- [ ] tests/test_claude_executor.py: 13 tests
- [ ] **PHASE 15 GATE**
```

**Also update the Phase Verification Gates section to add Phase 15 gate:**

```markdown
### Phase 15 Gate

```bash
# 1. Imports
python -c "from harness.services.claude_executor import is_claude_available; print('claude:', is_claude_available())"

# 2. Config fields
python -c "
from harness.config import HarnessConfig
c = HarnessConfig(project_name='x', llm_provider='anthropic', llm_model='m')
assert c.use_claude_code == True
assert c.claude_code_timeout == 300
print('config OK')
"

# 3. All 13 executor tests pass
pytest tests/test_claude_executor.py -v

# 4. Full suite green
pytest tests/ -q

# 5. CLI config set works
harness config set use_claude_code true
harness config set use_claude_code false
harness config set claude_code_timeout 120
```

---

## End-to-End Verification

After all 9 phases complete, run this in the LeetCodeFake project:

```bash
cd /home/fionn/Documents/Dev/LeetCodeFake/API/api-service

# Enable Claude Code mode
harness config set use_claude_code true

# Check status (should be CONTRACT_READY or earlier)
harness status

# If CONTRACT_READY, implement
harness implement C001
# Expected output:
#   Syntax Executor: Claude Code CLI
#   [Claude Code runs — 30–120s]
#   Patch generated via Claude Code
#   File: .harness/patches/C001.diff
#   Lines: <N>

# Verify real files were written
ls src/main/java/com/leetcodefake/problem/
# Expected: ProblemController.java, TestCaseService.java, dto/...

# Verify diff was captured correctly
head -20 .harness/patches/C001.diff
# Expected: proper unified diff with +++ b/src/main/java/... headers

# Review the diff
harness implement C001  # or: cat .harness/patches/C001.diff

# Approve
harness apply
# Expected:
#   Patch approved.
#   Files are already written to disk by Claude Code.

# Compliance check
harness check C001
# Expected: compliance report against the real diff

# git diff to see actual state
git diff
# Should match the patch
```

---

## Invariants That Must Hold After Integration

These rules are in CLAUDE.md and must not be violated:

1. **Services never import from `cli.py`** — `claude_executor.py` imports only stdlib
2. **State machine raises, never warns** — unchanged
3. **Patch files go to `.harness/patches/`** — `capture_diff_staged` output still written there
4. **Compliance check runs before `git apply`** — files are written but users still approve
5. **All LLM output via `model_validate_json()`** — unchanged; Claude Code output is not parsed as JSON
6. **Prompt templates in `harness/prompts/*.md`** — `build_impl_prompt` is an exception: it's programmatic because the constraint structure is dynamic per-contract

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Claude Code writes files outside `allowed_files` | Low | High | Compliance rule-based check catches `scope_violation` |
| Claude Code times out on large contracts | Medium | Medium | `claude_code_timeout` config field; default 300s is generous |
| `git diff --cached` empty (no changes) | Low | Medium | `LLMOutputError("no changes")` raised; user retries |
| Project has no git repo (no git apply possible) | Medium | Low | `capture_diff_staged` returns empty; error message tells user |
| Claude Code billing cost per implement call | High | Low | Documented; user controls when to trigger |
| `reset_allowed_files` fails (file locked) | Very Low | Low | `check=False` — failure logged to stderr, not fatal |

---

## Files Summary

| File | Action | Lines changed (est.) |
|------|--------|---------------------|
| `harness/config.py` | Modify — +2 fields | +2 |
| `harness/services/claude_executor.py` | **Create** | ~110 |
| `harness/services/implementation_service.py` | Modify — dispatch logic | ~50 |
| `harness/runtime.py` | Modify — `config=config` ×2 | +2 |
| `harness/cli.py` | Modify — 3 changes | ~25 |
| `harness/server.py` | Modify — `config=config` ×1 | +1 |
| `harness/app.py` | Modify — badge + button + config | ~40 |
| `tests/test_claude_executor.py` | **Create** | ~130 |
| `CLAUDE.md` | Modify — Phase 15 entry | ~15 |

**Total: ~375 lines added/changed. Zero lines deleted from existing logic (LLM path kept intact).**
