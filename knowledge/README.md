# Knowledge Base — Architect-Driven Coding Harness

Reference library for building and understanding the Harness system.

| File | Contents |
|------|----------|
| [01_product_vision.md](01_product_vision.md) | What this product is, positioning, target users |
| [02_core_loop.md](02_core_loop.md) | Ask→Decide→Contract→Syntax→Check→Remember explained |
| [03_decision_taxonomy.md](03_decision_taxonomy.md) | 15 decision categories with examples |
| [04_state_machine.md](04_state_machine.md) | 9 states, transitions, forbidden paths |
| [05_db_schema.md](05_db_schema.md) | SQLite tables, ID generation, query patterns |
| [06_architecture.md](06_architecture.md) | Module dependency graph, layer rules |
| [07_prompt_patterns.md](07_prompt_patterns.md) | SK-1 through SK-5 reusable patterns |
| [08_cli_reference.md](08_cli_reference.md) | All 13 commands with signatures and examples |
| [09_compliance_rules.md](09_compliance_rules.md) | Two-phase compliance, violation types |
| [10_memory_system.md](10_memory_system.md) | Memory types, upsert pattern, conflict detection |
| [AGENT_LOOP.md](AGENT_LOOP.md) | Autonomous continuation prompt and instructions |

## Quick Reference

**Build order:** schemas → config → db → state_machine → llm → services → cli

**Core constraint:** AI never writes code without a Contract. Contract never exists without approved Decisions.

**Active phase:** See `CLAUDE.md` in project root for current progress.
