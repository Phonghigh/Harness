# Testing Conventions

## Running Tests

```bash
pytest tests/ -q          # full suite — must be green before any commit
pytest tests/ -v          # verbose output
pytest tests/test_X.py    # single file
```

## Test Suite (69 tests across 8 files)

| File | Coverage |
|------|----------|
| tests/test_state_machine.py | State transitions, invalid transition errors |
| tests/test_decision.py | Decision creation, approval, conflict detection |
| tests/test_contract.py | Contract building, decision_ids population |
| tests/test_validation.py | Compliance report, error/warning counts |
| tests/test_memory.py | Memory upsert, category, applied_count, source_task_id |
| tests/test_runtime.py | PauseReason, RuntimeResult, run_until_pause (4 tests) |
| tests/test_llm.py | Retry loop, _is_retriable, token tracking (4 tests) |
| tests/test_claude_executor.py | is_claude_available, build_impl_prompt, run_claude_implement, capture_diff_staged (13 tests) |

## Rules

- pytest must pass green before every commit — no exceptions
- New service functions need at least a smoke test
- Tests live in `tests/` at repo root — never inside `harness/`
- Do not mock the database in integration tests; use `tempfile.TemporaryDirectory()`
