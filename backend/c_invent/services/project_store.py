import sqlite3, json, uuid, os
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.getenv("CINVENT_DB_PATH", "data/cinvent.db"))

class ProjectStore:
    def __init__(self, path=DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._init()

    def conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def _init(self):
        with self.conn() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS projects(
                id TEXT PRIMARY KEY, name TEXT, domain TEXT, description TEXT,
                created_at TEXT, updated_at TEXT, source TEXT DEFAULT 'legacy', platform_config_json TEXT DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS documents(
                id TEXT PRIMARY KEY, project_id TEXT, name TEXT, mime_type TEXT,
                size_bytes INTEGER, text TEXT, metadata_json TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS artifacts(
                id TEXT PRIMARY KEY, project_id TEXT, kind TEXT, name TEXT,
                language TEXT, content TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS runs(
                id TEXT PRIMARY KEY, project_id TEXT, agent TEXT, status TEXT,
                input_text TEXT, output_json TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS approvals(
                id TEXT PRIMARY KEY, project_id TEXT, artifact_type TEXT,
                status TEXT, comment TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS audit(
                id TEXT PRIMARY KEY, project_id TEXT, action TEXT,
                status TEXT, details TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS executions(
                id TEXT PRIMARY KEY, project_id TEXT, stage TEXT, status TEXT,
                current_step TEXT, total_steps INTEGER DEFAULT 1, completed_steps INTEGER DEFAULT 0,
                message TEXT, started_at TEXT, updated_at TEXT, finished_at TEXT,
                error_json TEXT, trace_json TEXT DEFAULT '[]');
            """)
            # Backward-compatible migration for databases created before 0.1.9.
            cols = {row[1] for row in c.execute("PRAGMA table_info(projects)").fetchall()}
            if "source" not in cols:
                c.execute("ALTER TABLE projects ADD COLUMN source TEXT DEFAULT 'legacy'")
            if "platform_config_json" not in cols:
                c.execute("ALTER TABLE projects ADD COLUMN platform_config_json TEXT DEFAULT '{}'")

    def now(self): return datetime.now(timezone.utc).isoformat()

    def create_execution(self, pid, stage, total_steps=1, message="Queued"):
        execution_id = str(uuid.uuid4())
        now = self.now()
        trace = [{"timestamp": now, "step": stage, "status": "queued", "message": message}]
        with self.conn() as c:
            c.execute(
                "INSERT INTO executions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (execution_id, pid, stage, "queued", "", int(total_steps), 0, message, now, now, None, None, json.dumps(trace)),
            )
        return execution_id

    def get_execution(self, execution_id):
        with self.conn() as c:
            row = c.execute("SELECT * FROM executions WHERE id=?", (execution_id,)).fetchone()
            if not row:
                return None
            item = dict(row)
            for field, default in (("trace_json", []), ("error_json", None)):
                raw = item.get(field)
                try:
                    item[field.replace("_json", "")] = json.loads(raw) if raw else default
                except Exception:
                    item[field.replace("_json", "")] = default
            item.pop("trace_json", None)
            item.pop("error_json", None)
            try:
                started = datetime.fromisoformat(item.get("started_at"))
                end_value = item.get("finished_at") or self.now()
                ended = datetime.fromisoformat(end_value)
                item["elapsed_seconds"] = max(0, int((ended - started).total_seconds()))
            except Exception:
                item["elapsed_seconds"] = 0
            return item

    def latest_execution(self, pid, stage=None):
        with self.conn() as c:
            if stage:
                row = c.execute(
                    "SELECT id FROM executions WHERE project_id=? AND stage=? ORDER BY started_at DESC LIMIT 1",
                    (pid, stage),
                ).fetchone()
            else:
                row = c.execute(
                    "SELECT id FROM executions WHERE project_id=? ORDER BY started_at DESC LIMIT 1",
                    (pid,),
                ).fetchone()
        return self.get_execution(row[0]) if row else None

    def recover_stale_executions(self, max_age_minutes=30):
        """Mark abandoned in-process executions as failed after a safe timeout.

        Render/container restarts can terminate FastAPI BackgroundTasks. Without
        recovery, the old RUNNING row would permanently block the same stage.
        A generous timeout avoids treating a genuinely long provider call as
        stale while still preventing zombie executions.
        """
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
        with self.conn() as c:
            rows = c.execute(
                "SELECT id, started_at FROM executions WHERE status IN ('queued','running')"
            ).fetchall()
            for row in rows:
                try:
                    started = datetime.fromisoformat(row[1])
                except Exception:
                    continue
                if started < cutoff:
                    now = self.now()
                    item = self.get_execution(row[0])
                    trace = list(item.get("trace") or []) if item else []
                    trace.append({"timestamp": now, "step": item.get("current_step") if item else "unknown", "status": "failed", "phase": "recovered", "message": "Execution abandoned after application restart or timeout."})
                    c.execute(
                        "UPDATE executions SET status='failed', message=?, updated_at=?, finished_at=?, error_json=?, trace_json=? WHERE id=?",
                        ("Execution was recovered as failed because the previous worker is no longer active.", now, now, json.dumps({"code":"STALE_EXECUTION_RECOVERED"}), json.dumps(trace, ensure_ascii=False), row[0])
                    )

    def active_execution(self, pid, stage=None):
        with self.conn() as c:
            statuses = ("queued", "running")
            if stage:
                row = c.execute(
                    "SELECT id FROM executions WHERE project_id=? AND stage=? AND status IN (?,?) ORDER BY started_at DESC LIMIT 1",
                    (pid, stage, *statuses),
                ).fetchone()
            else:
                row = c.execute(
                    "SELECT id FROM executions WHERE project_id=? AND status IN (?,?) ORDER BY started_at DESC LIMIT 1",
                    (pid, *statuses),
                ).fetchone()
        return self.get_execution(row[0]) if row else None

    def update_execution(self, execution_id, status=None, current_step=None, completed_steps=None,
                         message=None, trace_event=None, error=None, finished=False):
        current = self.get_execution(execution_id)
        if not current:
            return None
        trace = list(current.get("trace") or [])
        now = self.now()
        if trace_event:
            event = {"timestamp": now, **trace_event}
            trace.append(event)
        new_status = status or current.get("status")
        finished_at = now if finished or new_status in {"success", "failed", "blocked", "cancelled"} else current.get("finished_at")
        error_json = json.dumps(error, ensure_ascii=False) if error is not None else None
        with self.conn() as c:
            c.execute(
                "UPDATE executions SET status=?, current_step=?, completed_steps=?, message=?, updated_at=?, finished_at=?, error_json=?, trace_json=? WHERE id=?",
                (
                    new_status,
                    current_step if current_step is not None else current.get("current_step", ""),
                    int(completed_steps if completed_steps is not None else current.get("completed_steps", 0)),
                    message if message is not None else current.get("message", ""),
                    now, finished_at, error_json if error is not None else (json.dumps(current.get("error"), ensure_ascii=False) if current.get("error") else None),
                    json.dumps(trace, ensure_ascii=False), execution_id,
                ),
            )
        return self.get_execution(execution_id)

    def executions(self, pid, limit=20):
        with self.conn() as c:
            rows = c.execute(
                "SELECT id FROM executions WHERE project_id=? ORDER BY started_at DESC LIMIT ?",
                (pid, int(limit)),
            ).fetchall()
        return [self.get_execution(r[0]) for r in rows]

    def create_project(self, name, domain="", description="", source="user"):
        pid = str(uuid.uuid4())
        now = self.now()
        with self.conn() as c:
            c.execute("INSERT INTO projects(id,name,domain,description,created_at,updated_at,source) VALUES(?,?,?,?,?,?,?)",
                      (pid, name, domain, description, now, now, source))
        return pid

    def ensure_single_clean_workspace(self):
        """One-time-safe cleanup of legacy auto-created blank Untitled projects.

        Only projects with no customer evidence/artifacts/runs/approvals and whose
        source is legacy/system are eligible. Explicit user-created projects are
        never removed. Returns the retained project id, if any.
        """
        with self.conn() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT * FROM projects WHERE source IN ('legacy','system') "
                "AND (name='Untitled Customer Project' OR name IS NULL OR name='') "
                "ORDER BY updated_at DESC"
            )]
            if not rows:
                return None
            keep = rows[0]
            for p in rows[1:]:
                pid = p["id"]
                has_data = any([
                    c.execute("SELECT 1 FROM documents WHERE project_id=? LIMIT 1", (pid,)).fetchone(),
                    c.execute("SELECT 1 FROM artifacts WHERE project_id=? LIMIT 1", (pid,)).fetchone(),
                    c.execute("SELECT 1 FROM runs WHERE project_id=? LIMIT 1", (pid,)).fetchone(),
                    c.execute("SELECT 1 FROM approvals WHERE project_id=? LIMIT 1", (pid,)).fetchone(),
                    c.execute("SELECT 1 FROM audit WHERE project_id=? LIMIT 1", (pid,)).fetchone(),
                ])
                if not has_data:
                    c.execute("DELETE FROM projects WHERE id=?", (pid,))
            # The retained legacy project becomes the stable system seed.
            c.execute("UPDATE projects SET source='system' WHERE id=?", (keep["id"],))
            return keep["id"]


    def migrate_untitled_projects(self):
        """Make the project list customer-facing without deleting evidence.

        C INVENT never creates a project on startup. Any POC-era "Untitled
        Customer Project" is renamed in place. Evidence-bearing projects are
        retained with their existing id/history; empty placeholders are retained
        only when they are explicitly user-created. Legacy/system duplicates that
        are truly empty are consolidated to one named system starter.
        """
        with self.conn() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT * FROM projects WHERE name IS NULL OR TRIM(name)='' OR name='Untitled Customer Project' "
                "ORDER BY updated_at DESC"
            )]
            if not rows:
                return

            empty_legacy = []
            for p in rows:
                pid = p["id"]
                has_data = any([
                    c.execute("SELECT 1 FROM documents WHERE project_id=? LIMIT 1", (pid,)).fetchone(),
                    c.execute("SELECT 1 FROM artifacts WHERE project_id=? LIMIT 1", (pid,)).fetchone(),
                    c.execute("SELECT 1 FROM runs WHERE project_id=? LIMIT 1", (pid,)).fetchone(),
                    c.execute("SELECT 1 FROM approvals WHERE project_id=? LIMIT 1", (pid,)).fetchone(),
                    c.execute("SELECT 1 FROM audit WHERE project_id=? LIMIT 1", (pid,)).fetchone(),
                    bool((p.get("description") or "").strip()),
                ])
                if not has_data and p.get("source") in ("legacy", "system"):
                    empty_legacy.append(p)

            keep = empty_legacy[0] if empty_legacy else None
            for p in empty_legacy[1:]:
                c.execute("DELETE FROM projects WHERE id=?", (p["id"],))
            if keep:
                c.execute(
                    "UPDATE projects SET name='New Customer Project', source='system', updated_at=? WHERE id=?",
                    (self.now(), keep["id"]),
                )

            used_names = {r[0] for r in c.execute("SELECT name FROM projects WHERE name IS NOT NULL AND name <> 'Untitled Customer Project'").fetchall()}
            for p in rows:
                pid = p["id"]
                exists = c.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone()
                if not exists:
                    continue
                current = c.execute("SELECT name,domain,description FROM projects WHERE id=?", (pid,)).fetchone()
                if current and current[0] not in (None, "", "Untitled Customer Project"):
                    continue
                domain = (current[1] or p.get("domain") or "").strip()
                description = (current[2] or p.get("description") or "").strip()
                has_data = any([
                    c.execute("SELECT 1 FROM documents WHERE project_id=? LIMIT 1", (pid,)).fetchone(),
                    c.execute("SELECT 1 FROM artifacts WHERE project_id=? LIMIT 1", (pid,)).fetchone(),
                    c.execute("SELECT 1 FROM runs WHERE project_id=? LIMIT 1", (pid,)).fetchone(),
                    c.execute("SELECT 1 FROM approvals WHERE project_id=? LIMIT 1", (pid,)).fetchone(),
                    c.execute("SELECT 1 FROM audit WHERE project_id=? LIMIT 1", (pid,)).fetchone(),
                    bool(description),
                ])
                # Never leave an Untitled Customer Project visible. Preserve the
                # project id/evidence and give legacy/user placeholders a safe name.
                # Explicitly created named projects are untouched.
                if domain and domain.lower() != "unknown":
                    base = f"{domain} Modernization Project"
                else:
                    base = "Customer Modernization Project" if has_data else "New Customer Project"
                name = base
                if name in used_names:
                    name = f"{base} · {pid[:8]}"
                used_names.add(name)
                c.execute("UPDATE projects SET name=?, updated_at=? WHERE id=?", (name, self.now(), pid))

    def list_projects(self):
        with self.conn() as c:
            return [dict(x) for x in c.execute("SELECT * FROM projects ORDER BY updated_at DESC")]

    def reset_workspace(self):
        """Clear all local POC data so a fresh delivery project can be started."""
        with self.conn() as c:
            c.execute("DELETE FROM audit")
            c.execute("DELETE FROM approvals")
            c.execute("DELETE FROM runs")
            c.execute("DELETE FROM artifacts")
            c.execute("DELETE FROM documents")
            c.execute("DELETE FROM projects")

    def get_project(self, pid):
        with self.conn() as c:
            x = c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
            if not x:
                return {}
            item = dict(x)
            try:
                item["platform_config"] = json.loads(item.get("platform_config_json") or "{}")
            except Exception:
                item["platform_config"] = {}
            return item

    def get_platform_config(self, pid):
        """Return project-owned platform configuration, never POC/global config."""
        project = self.get_project(pid)
        if not project:
            return {}
        return project.get("platform_config") or {}

    def save_platform_config(self, pid, config):
        config = config or {}
        with self.conn() as c:
            c.execute("UPDATE projects SET platform_config_json=?, updated_at=? WHERE id=?",
                      (json.dumps(config, ensure_ascii=False), self.now(), pid))

    def update_project(self, pid, name=None, domain=None, description=None):
        p = self.get_project(pid)
        with self.conn() as c:
            c.execute("UPDATE projects SET name=?,domain=?,description=?,updated_at=? WHERE id=?",
                      (name if name is not None else p["name"],
                       domain if domain is not None else p["domain"],
                       description if description is not None else p["description"],
                       self.now(), pid))

    def save_document(self, pid, name, mime, size, text, metadata):
        with self.conn() as c:
            c.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?,?)",
                      (str(uuid.uuid4()), pid, name, mime, size, text, json.dumps(metadata), self.now()))

    def document_exists(self, pid, name):
        with self.conn() as c:
            return c.execute("SELECT 1 FROM documents WHERE project_id=? AND name=?", (pid, name)).fetchone() is not None

    def documents(self, pid):
        with self.conn() as c:
            return [dict(x) for x in c.execute("SELECT * FROM documents WHERE project_id=? ORDER BY created_at", (pid,))]

    def save_artifact(self, pid, kind, name, language, content):
        with self.conn() as c:
            c.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)",
                      (str(uuid.uuid4()), pid, kind, name, language, content, self.now()))

    def artifacts(self, pid):
        with self.conn() as c:
            return [dict(x) for x in c.execute("SELECT * FROM artifacts WHERE project_id=? ORDER BY created_at DESC", (pid,))]

    def save_run(self, pid, agent, status, input_text, output):
        with self.conn() as c:
            c.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)",
                      (str(uuid.uuid4()), pid, agent, status, input_text, json.dumps(output), self.now()))


    def latest_run(self, pid, agent, success_only=True):
        with self.conn() as c:
            q = "SELECT * FROM runs WHERE project_id=? AND agent=?"
            params = [pid, agent]
            if success_only:
                q += " AND status='success'"
            q += " ORDER BY created_at DESC LIMIT 1"
            row = c.execute(q, params).fetchone()
            if not row:
                return None
            item = dict(row)
            try:
                item["output"] = json.loads(item["output_json"])
            except Exception:
                item["output"] = item["output_json"]
            return item

    def add_approval(self, pid, artifact_type, comment):
        with self.conn() as c:
            c.execute("INSERT INTO approvals VALUES(?,?,?,?,?,?)",
                      (str(uuid.uuid4()), pid, artifact_type, "APPROVED", comment, self.now()))

    def latest_approval(self, pid, artifact_type, approved_only=True):
        with self.conn() as c:
            q = "SELECT * FROM approvals WHERE project_id=? AND artifact_type=?"
            params = [pid, artifact_type]
            if approved_only:
                q += " AND status='APPROVED'"
            q += " ORDER BY created_at DESC LIMIT 1"
            row = c.execute(q, params).fetchone()
            return dict(row) if row else None

    def latest_artifact(self, pid, kind):
        with self.conn() as c:
            row = c.execute(
                "SELECT * FROM artifacts WHERE project_id=? AND kind=? ORDER BY created_at DESC LIMIT 1",
                (pid, kind),
            ).fetchone()
            return dict(row) if row else None

    def artifact_exists(self, pid, kind):
        return self.latest_artifact(pid, kind) is not None

    def add_audit(self, pid, action, status, details=""):
        with self.conn() as c:
            c.execute("INSERT INTO audit VALUES(?,?,?,?,?,?)",
                      (str(uuid.uuid4()), pid, action, status, details, self.now()))

    def audit(self, pid):
        with self.conn() as c:
            return [dict(x) for x in c.execute("SELECT * FROM audit WHERE project_id=? ORDER BY created_at DESC", (pid,))]

    def count_documents(self,pid): return len(self.documents(pid))
    def count_artifacts(self,pid): return len(self.artifacts(pid))
    def count_runs(self,pid):
        with self.conn() as c: return c.execute("SELECT COUNT(*) FROM runs WHERE project_id=?", (pid,)).fetchone()[0]
    def count_approvals(self,pid):
        with self.conn() as c: return c.execute("SELECT COUNT(*) FROM approvals WHERE project_id=?", (pid,)).fetchone()[0]
    def lifecycle_progress(self,pid):
        with self.conn() as c:
            n=c.execute("SELECT COUNT(DISTINCT agent) FROM runs WHERE project_id=? AND status='success'", (pid,)).fetchone()[0]
        return min(9,n)
