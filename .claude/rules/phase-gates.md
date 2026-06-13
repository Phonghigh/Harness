# Phase Verification Gates

## Phase 1 Gate
All commands must work with NO API KEY set (stubs only).

```bash
harness init --provider anthropic --model claude-sonnet-4-6
harness start "Add product CRUD"
harness status
harness interrogate         # → [STUB] decisions generated
harness decisions
harness answer D001 "Use DTO"
harness approve D001
harness contract            # → [STUB] C001 created
harness implement C001      # → patch written (stub)
harness check C001          # → [STUB] PASS
harness validate            # → DONE
harness remember            # → [STUB] memories
harness memory list
```

## Phase 2 Gate
Requires real API key.

```bash
export HARNESS_PROVIDER=anthropic
export ANTHROPIC_API_KEY=<key>
harness start "Add user login with JWT"
harness interrogate         # → real 6-10 decisions
harness answer D001 "JWT RS256"
# ... answer remaining
harness approve --all
harness contract            # → real contract JSON
harness implement C001      # → real .diff file in .harness/patches/
harness check C001          # → rule-based + LLM compliance report
harness validate
harness remember
harness memory list         # → real memory entries
```

## Phase 15 Gate

```bash
python -c "from harness.services.claude_executor import is_claude_available; print('claude:', is_claude_available())"
python -c "from harness.config import HarnessConfig; c = HarnessConfig(project_name='x', llm_provider='anthropic', llm_model='m'); assert c.use_claude_code == True; print('config OK')"
pytest tests/test_claude_executor.py -v
pytest tests/ -q
harness config set use_claude_code true
harness config set claude_code_timeout 120
```

# Task Verification Commands

```bash
# schemas/compliance.py
python -c "from harness.schemas.compliance import ComplianceReport, Violation; print('OK')"

# config.py
python -c "from harness.config import find_harness_root, HarnessConfig; print('OK')"

# db.py
python -c "
from harness.db import Database
from pathlib import Path
import tempfile
with tempfile.TemporaryDirectory() as d:
    db = Database(Path(d) / 'test.db')
    db.initialize()
    print('DB OK')
"

# state_machine.py
python -c "
from harness.state_machine import validate_transition, assert_command_allowed, InvalidTransitionError
from harness.schemas.task import TaskStatus
validate_transition(TaskStatus.INTAKE, TaskStatus.INTERROGATING)
try:
    validate_transition(TaskStatus.INTAKE, TaskStatus.IMPLEMENTING)
    print('FAIL')
except InvalidTransitionError as e:
    print('State machine OK:', e)
"

# services
python -c "from harness.services.task_service import create_task; print('task_service OK')"
python -c "from harness.services.decision_service import list_decisions; print('decision_service OK')"
python -c "from harness.services.contract_service import build_contract; print('contract_service OK')"

# cli
harness --help
```
