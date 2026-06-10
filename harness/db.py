import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id              TEXT PRIMARY KEY,
                    title           TEXT NOT NULL,
                    raw_requirement TEXT NOT NULL,
                    status          TEXT NOT NULL,
                    created_at      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS decisions (
                    id              TEXT PRIMARY KEY,
                    task_id         TEXT NOT NULL,
                    category        TEXT NOT NULL,
                    question        TEXT NOT NULL,
                    options_json    TEXT NOT NULL,
                    recommendation  TEXT,
                    selected_answer TEXT,
                    status          TEXT NOT NULL DEFAULT 'pending',
                    created_at      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES tasks(id)
                );

                CREATE TABLE IF NOT EXISTS contracts (
                    id                 TEXT PRIMARY KEY,
                    task_id            TEXT NOT NULL,
                    scope              TEXT NOT NULL,
                    allowed_files_json TEXT NOT NULL,
                    forbidden_json     TEXT NOT NULL,
                    spec_json          TEXT NOT NULL,
                    status             TEXT NOT NULL DEFAULT 'draft',
                    created_at         TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES tasks(id)
                );

                CREATE TABLE IF NOT EXISTS patches (
                    id          TEXT PRIMARY KEY,
                    contract_id TEXT NOT NULL,
                    diff_text   TEXT NOT NULL,
                    status      TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    FOREIGN KEY (contract_id) REFERENCES contracts(id)
                );

                CREATE TABLE IF NOT EXISTS compliance_reports (
                    id              TEXT PRIMARY KEY,
                    contract_id     TEXT NOT NULL,
                    patch_id        TEXT NOT NULL,
                    passed          INTEGER NOT NULL,
                    violations_json TEXT,
                    summary         TEXT,
                    created_at      TEXT NOT NULL,
                    FOREIGN KEY (contract_id) REFERENCES contracts(id),
                    FOREIGN KEY (patch_id)    REFERENCES patches(id)
                );

                CREATE TABLE IF NOT EXISTS memory (
                    id          TEXT PRIMARY KEY,
                    type        TEXT NOT NULL,
                    scope       TEXT NOT NULL,
                    key         TEXT NOT NULL,
                    value_json  TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL,
                    UNIQUE(type, scope, key)
                );
            """)

    # --- Tasks ---

    def create_task(self, task: dict) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO tasks (id, title, raw_requirement, status, created_at, updated_at)"
                " VALUES (:id, :title, :raw_requirement, :status, :created_at, :updated_at)",
                task,
            )

    def get_active_task(self) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM tasks WHERE status != 'DONE' LIMIT 1"
            ).fetchone()

    def get_latest_task(self) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT 1"
            ).fetchone()

    def get_task(self, task_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()

    def update_task_status(self, task_id: str, status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (status, now_iso(), task_id),
            )

    # --- Decisions ---

    def create_decision(self, decision: dict) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO decisions"
                " (id, task_id, category, question, options_json, recommendation,"
                "  selected_answer, status, created_at, updated_at)"
                " VALUES (:id, :task_id, :category, :question, :options_json, :recommendation,"
                "         :selected_answer, :status, :created_at, :updated_at)",
                decision,
            )

    def get_decisions(self, task_id: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM decisions WHERE task_id = ? ORDER BY id", (task_id,)
            ).fetchall()

    def get_decision(self, decision_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM decisions WHERE id = ?", (decision_id,)
            ).fetchone()

    def update_decision(self, decision_id: str, updates: dict) -> None:
        set_clauses = ", ".join(f"{k} = ?" for k in updates)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE decisions SET {set_clauses} WHERE id = ?",
                [*updates.values(), decision_id],
            )

    def get_pending_decisions(self, task_id: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM decisions WHERE task_id = ? AND status != 'approved'",
                (task_id,),
            ).fetchall()

    def count_decisions(self, task_id: str) -> int:
        with self.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM decisions WHERE task_id = ?", (task_id,)
            ).fetchone()[0]

    # --- Contracts ---

    def create_contract(self, contract: dict) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO contracts"
                " (id, task_id, scope, allowed_files_json, forbidden_json, spec_json, status, created_at)"
                " VALUES (:id, :task_id, :scope, :allowed_files_json, :forbidden_json, :spec_json, :status, :created_at)",
                contract,
            )

    def get_contract(self, contract_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM contracts WHERE id = ?", (contract_id,)
            ).fetchone()

    def get_latest_contract(self, task_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM contracts WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
                (task_id,),
            ).fetchone()

    def count_contracts(self) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM contracts").fetchone()[0]

    def update_contract_status(self, contract_id: str, status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE contracts SET status = ? WHERE id = ?", (status, contract_id)
            )

    # --- Patches ---

    def create_patch(self, patch: dict) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO patches (id, contract_id, diff_text, status, created_at)"
                " VALUES (:id, :contract_id, :diff_text, :status, :created_at)",
                patch,
            )

    def get_patch(self, patch_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM patches WHERE id = ?", (patch_id,)
            ).fetchone()

    def get_latest_patch(self, contract_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM patches WHERE contract_id = ? ORDER BY created_at DESC LIMIT 1",
                (contract_id,),
            ).fetchone()

    def count_patches(self) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM patches").fetchone()[0]

    # --- Compliance ---

    def create_compliance_report(self, report: dict) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO compliance_reports"
                " (id, contract_id, patch_id, passed, violations_json, summary, created_at)"
                " VALUES (:id, :contract_id, :patch_id, :passed, :violations_json, :summary, :created_at)",
                report,
            )

    def count_compliance_reports(self) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM compliance_reports").fetchone()[0]

    # --- Memory ---

    def upsert_memory(self, entry: dict) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO memory (id, type, scope, key, value_json, created_at, updated_at)
                VALUES (:id, :type, :scope, :key, :value_json, :created_at, :updated_at)
                ON CONFLICT(type, scope, key)
                DO UPDATE SET value_json = excluded.value_json,
                             updated_at  = excluded.updated_at
                """,
                entry,
            )

    def list_memory(
        self,
        type_filter: str | None = None,
        scope_filter: str | None = None,
    ) -> list[sqlite3.Row]:
        conditions: list[str] = []
        params: list = []
        if type_filter:
            conditions.append("type = ?")
            params.append(type_filter)
        if scope_filter:
            conditions.append("scope = ?")
            params.append(scope_filter)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        with self.connect() as conn:
            return conn.execute(
                f"SELECT * FROM memory{where} ORDER BY created_at", params
            ).fetchall()

    def delete_memory(self, memory_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM memory WHERE id = ?", (memory_id,))
        return cur.rowcount > 0

    # --- ID generation ---

    @staticmethod
    def new_task_id() -> str:
        return "T" + uuid.uuid4().hex[:6].upper()

    def new_decision_id(self, task_id: str) -> str:
        return f"D{self.count_decisions(task_id) + 1:03d}"

    def new_contract_id(self) -> str:
        return f"C{self.count_contracts() + 1:03d}"

    def new_patch_id(self) -> str:
        return f"P{self.count_patches() + 1:03d}"

    def new_compliance_report_id(self) -> str:
        return f"R{self.count_compliance_reports() + 1:03d}"

    @staticmethod
    def new_memory_id() -> str:
        return "M" + uuid.uuid4().hex[:8].upper()
