"""Harness Streamlit dashboard — run with: streamlit run harness/app.py"""
import json
import os
import sys
from pathlib import Path

import streamlit as st

# ── page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Harness",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── helpers ───────────────────────────────────────────────────────────────────

def _resolve_project(path_str: str):
    """Return (harness_dir, config, db) or None if not initialised."""
    from harness.config import find_harness_root, HarnessConfig
    from harness.db import Database
    import json

    root = Path(path_str).expanduser().resolve()
    if not root.exists():
        return None
    harness_dir = find_harness_root(root)
    if harness_dir is None:
        return None
    cfg_data = json.loads((harness_dir / "config.json").read_text())
    config = HarnessConfig.model_validate(cfg_data)
    db = Database(harness_dir / "harness.db")
    db.initialize()
    return harness_dir, config, db


def _get_llm(config):
    from harness.config import EnvSettings
    from harness.llm import build_adapter
    env = EnvSettings()
    provider = env.harness_provider or config.llm_provider
    has_key = (
        (provider == "anthropic" and env.anthropic_api_key)
        or (provider == "openai" and env.openai_api_key)
    )
    if not has_key:
        return None
    return build_adapter(
        config.llm_provider, config.llm_model,
        max_tokens=config.max_tokens, retries=config.llm_retries,
    )


def _status_badge(status: str) -> str:
    colors = {
        "INTAKE": "🟡",
        "INTERROGATING": "🔵",
        "WAITING_FOR_DECISIONS": "🟠",
        "DECISIONS_APPROVED": "🟢",
        "WAITING_FOR_CONTRACT_APPROVAL": "🟠",
        "CONTRACT_READY": "🟢",
        "WAITING_FOR_PATCH_APPROVAL": "🟠",
        "IMPLEMENTING": "🔵",
        "CHECKING_COMPLIANCE": "🔵",
        "VALIDATING": "🔵",
        "DONE": "✅",
    }
    return colors.get(status, "⚪") + " " + status


# ── sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🏗️ Harness")

    project_path = st.text_input(
        "Project path",
        value=st.session_state.get("project_path", os.getcwd()),
        placeholder="/path/to/your/project",
    )
    st.session_state["project_path"] = project_path

    ctx = _resolve_project(project_path)

    if ctx is None:
        st.error("No `.harness/` found. Run `harness init` in this directory first.")
        st.code(f"cd {project_path}\nharness init --provider openai --model gpt-4o")
        st.stop()

    harness_dir, config, db = ctx

    # Show config
    with st.expander("⚙️ Config"):
        st.write(f"**Provider:** `{config.llm_provider}`")
        st.write(f"**Model:** `{config.llm_model}`")
        st.write(f"**Project:** `{config.project_name}`")

        api_key_var = "OPENAI_API_KEY" if config.llm_provider == "openai" else "ANTHROPIC_API_KEY"
        if not os.environ.get(api_key_var):
            st.warning(f"`{api_key_var}` not set — stub mode only")

    st.divider()

    page = st.radio(
        "Navigate",
        ["🚀 Start Task", "🗳️ Decisions", "📋 Contract", "🩹 Patch", "📜 History", "🧠 Memory"],
        label_visibility="collapsed",
    )

# ── active task helper ────────────────────────────────────────────────────────

task_row = db.get_active_task()
task = dict(task_row) if task_row else None

if task:
    st.caption(_status_badge(task["status"]) + f"  |  Task `{task['id']}`: {task['title']}")
    st.divider()

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: Start Task
# ═══════════════════════════════════════════════════════════════════════════════

if page == "🚀 Start Task":
    st.header("Start a Task")

    if task:
        st.info(f"Active task `{task['id']}` is in **{task['status']}** state. Complete or abandon it before starting a new one.")
        if st.button("⚠️ Abandon active task (mark DONE)", type="secondary"):
            from harness.db import now_iso
            db.update_task_status(task["id"], "DONE")
            st.rerun()
    else:
        with st.form("start_form"):
            requirement = st.text_area(
                "Requirement",
                placeholder="e.g. Add JWT authentication to the /login endpoint",
                height=120,
            )
            submitted = st.form_submit_button("▶ Start task", type="primary")

        if submitted and requirement.strip():
            from harness.services.task_service import create_task
            try:
                t = create_task(requirement.strip(), db)
                st.success(f"Task `{t['id']}` created. Go to **Decisions** to interrogate.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    # Interrogate section
    if task and task["status"] == "INTAKE":
        st.divider()
        st.subheader("Generate Decisions")
        llm = _get_llm(config)
        if llm is None:
            st.warning("No API key detected — will use stub decisions.")
        if st.button("🔍 Interrogate requirement", type="primary"):
            with st.spinner("Analysing requirement..."):
                if llm:
                    from harness.services.task_service import run_interrogate
                    run_interrogate(task, llm, db, harness_dir=harness_dir, config=config)
                else:
                    from harness.services.decision_service import generate_stub_decisions
                    generate_stub_decisions(task, db)
            st.success("Decisions generated! Go to **Decisions**.")
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: Decisions
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "🗳️ Decisions":
    st.header("Decisions")

    if not task:
        st.info("No active task. Start one first.")
        st.stop()

    decisions = [dict(d) for d in db.get_decisions(task["id"])]
    if not decisions:
        st.info("No decisions yet. Run interrogate from the **Start Task** page.")
        st.stop()

    pending = [d for d in decisions if d["status"] == "pending"]
    answered = [d for d in decisions if d["status"] == "answered"]
    approved = [d for d in decisions if d["status"] == "approved"]

    col1, col2, col3 = st.columns(3)
    col1.metric("Pending", len(pending))
    col2.metric("Answered", len(answered))
    col3.metric("Approved", len(approved))

    st.divider()

    # Answer pending decisions
    for d in pending:
        with st.expander(f"🟠 `{d['id']}` [{d['category']}] — {d['question']}", expanded=True):
            opts = json.loads(d["options_json"])
            rec = d.get("recommendation", "")
            st.caption(f"💡 Recommendation: {rec}")
            answer = st.radio("Choose or type your own:", opts + ["Custom..."], key=f"radio_{d['id']}", index=None)
            custom = ""
            if answer == "Custom...":
                custom = st.text_input("Your answer:", key=f"custom_{d['id']}")
            final = custom if answer == "Custom..." else (answer or "")
            if st.button(f"✅ Submit answer", key=f"submit_{d['id']}", disabled=not final):
                from harness.services.decision_service import answer_decision
                answer_decision(d["id"], final, task, db)
                task = dict(db.get_task(task["id"]))
                st.rerun()

    # Approve answered decisions
    if answered:
        st.divider()
        for d in answered:
            with st.expander(f"🟡 `{d['id']}` [{d['category']}] — answered", expanded=False):
                st.write(f"**Answer:** {d['selected_answer']}")
                if st.button(f"✅ Approve", key=f"approve_{d['id']}"):
                    from harness.services.decision_service import approve_decisions
                    approve_decisions([d["id"]], task, db)
                    task = dict(db.get_task(task["id"]))
                    st.rerun()

        st.divider()
        if st.button("✅ Approve All Answered", type="primary"):
            from harness.services.decision_service import approve_decisions
            approve_decisions([d["id"] for d in answered], task, db)
            task = dict(db.get_task(task["id"]))
            st.rerun()

    # Approved
    for d in approved:
        with st.expander(f"✅ `{d['id']}` [{d['category']}] — approved", expanded=False):
            st.write(f"**Answer:** {d['selected_answer']}")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: Contract
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "📋 Contract":
    st.header("Contract")

    if not task:
        st.info("No active task.")
        st.stop()

    c_row = db.get_latest_contract(task["id"])
    c = dict(c_row) if c_row else None

    # Build contract
    if task["status"] == "DECISIONS_APPROVED" and c is None:
        st.info("All decisions approved. Ready to build contract.")
        llm = _get_llm(config)
        if llm is None:
            st.warning("No API key — will generate stub contract.")
        if st.button("📋 Build Contract", type="primary"):
            with st.spinner("Building contract..."):
                from harness.services.contract_service import build_contract
                c = build_contract(task, db, llm, harness_dir=harness_dir, config=config)
            st.rerun()

    elif c is None:
        st.info(f"Task is in **{task['status']}**. Approve all decisions first.")
        st.stop()
    else:
        # Show contract
        spec = json.loads(c["spec_json"])
        st.subheader(f"`{c['id']}` — {c['scope']}")
        st.caption(f"Status: **{c['status']}**")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Files to change:**")
            for f in spec.get("files", []):
                action_icon = {"create": "🆕", "modify": "✏️", "delete": "🗑️"}.get(f["action"], "📄")
                st.markdown(f"- {action_icon} `{f['path']}` — {f['description']}")
        with col2:
            st.markdown("**Constraints:**")
            for constraint in spec.get("constraints", []):
                st.markdown(f"- {constraint}")

        st.markdown("**Acceptance criteria:**")
        for ac in spec.get("acceptance_criteria", []):
            st.markdown(f"- ✓ {ac}")

        # Approve/reject buttons
        if task["status"] == "WAITING_FOR_CONTRACT_APPROVAL":
            st.divider()
            col_a, col_r = st.columns(2)
            with col_a:
                if st.button("✅ Approve Contract", type="primary"):
                    from harness.services.contract_service import approve_contract
                    approve_contract(task, c["id"], db)
                    st.success("Contract approved! Go to **Patch** to implement.")
                    st.rerun()
            with col_r:
                if st.button("❌ Reject Contract", type="secondary"):
                    from harness.services.contract_service import reject_contract
                    reject_contract(task, db)
                    st.warning("Contract rejected. Task returned to DECISIONS_APPROVED.")
                    st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: Patch
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "🩹 Patch":
    st.header("Patch")

    if not task:
        st.info("No active task.")
        st.stop()

    c_row = db.get_latest_contract(task["id"])
    c = dict(c_row) if c_row else None

    if c is None:
        st.info("No contract yet. Build and approve a contract first.")
        st.stop()

    patch_row = db.get_latest_patch(c["id"])
    patch = dict(patch_row) if patch_row else None

    # Generate patch
    if task["status"] == "CONTRACT_READY" and patch is None:
        st.info("Contract approved. Ready to generate patch.")
        llm = _get_llm(config)
        if llm is None:
            st.warning("No API key — will generate stub patch.")
        if st.button("⚙️ Generate Patch", type="primary"):
            with st.spinner("Generating patch..."):
                from harness.services.implementation_service import implement
                implement(task, c, harness_dir, llm, db)
            st.rerun()

    elif patch is None:
        st.info(f"Task is in **{task['status']}**. Approve the contract first.")
        st.stop()
    else:
        # Show patch
        patch_file = harness_dir / "patches" / f"{c['id']}.diff"
        diff_text = patch_file.read_text() if patch_file.exists() else patch.get("diff_text", "")

        st.subheader(f"Patch for `{c['id']}`")
        st.caption(f"Status: **{patch['status']}**")

        st.code(diff_text, language="diff")

        if task["status"] == "WAITING_FOR_PATCH_APPROVAL":
            st.divider()
            col_a, col_r = st.columns(2)
            with col_a:
                if st.button("✅ Apply Patch", type="primary"):
                    from harness.services.implementation_service import approve_patch
                    approve_patch(task, db)
                    st.success("Patch approved → IMPLEMENTING. Run compliance check via CLI.")
                    st.rerun()
            with col_r:
                if st.button("❌ Reject Patch", type="secondary"):
                    from harness.services.implementation_service import reject_patch
                    reject_patch(task, c["id"], db)
                    st.warning("Patch rejected. Regenerate from Contract page.")
                    st.rerun()

        # Compliance result if available
        if task["status"] in ("IMPLEMENTING", "CHECKING_COMPLIANCE", "VALIDATING", "DONE"):
            report_row = db.get_latest_compliance_report(c["id"]) if hasattr(db, "get_latest_compliance_report") else None
            if report_row:
                r = dict(report_row)
                report_data = json.loads(r.get("report_json", "{}"))
                st.divider()
                st.subheader("Compliance Report")
                if report_data.get("passed"):
                    st.success(f"✅ PASS — {report_data.get('summary', '')}")
                else:
                    st.error(f"❌ FAIL — {report_data.get('summary', '')}")
                    for v in report_data.get("violations", []):
                        st.warning(f"**{v.get('severity','').upper()}** {v.get('description','')}")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: History
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "📜 History":
    st.header("Task History")

    tasks = db.list_tasks() if hasattr(db, "list_tasks") else []
    if not tasks:
        st.info("No completed tasks yet.")
        st.stop()

    for t in tasks:
        t = dict(t)
        badge = _status_badge(t["status"])
        with st.expander(f"{badge}  `{t['id']}` — {t['title']}", expanded=False):
            st.caption(f"Created: {t['created_at'][:10]}")
            decisions = db.get_decisions(t["id"])
            st.write(f"**Decisions:** {len(decisions)}")

            contract_row = db.get_latest_contract(t["id"])
            if contract_row:
                c = dict(contract_row)
                st.write(f"**Contract:** `{c['id']}` ({c['status']})")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: Memory
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "🧠 Memory":
    st.header("Architectural Memory")

    memories = db.list_memory()
    if not memories:
        st.info("No memories saved yet. Complete a task and run `harness remember`.")
        st.stop()

    search = st.text_input("🔍 Search memories", placeholder="Filter by key, type, or value...")

    for m in memories:
        m = dict(m)
        value = json.loads(m.get("value_json", "{}"))
        val_str = value if isinstance(value, str) else json.dumps(value)

        if search and search.lower() not in (m.get("key","") + val_str + m.get("type","")).lower():
            continue

        with st.expander(f"`{m['type']}` / **{m['key']}**", expanded=False):
            st.write(val_str)
            st.caption(f"Applied {m.get('applied_count', 0)}× | Updated {str(m.get('updated_at',''))[:10]}")
            if st.button("🗑️ Delete", key=f"del_{m['id']}"):
                db.delete_memory(m["id"])
                st.rerun()
