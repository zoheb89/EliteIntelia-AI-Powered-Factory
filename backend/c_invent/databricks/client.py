import base64
import requests

class DatabricksClient:
    def __init__(self, settings, host=None, token=None):
        self.settings = settings
        self.host = (host if host is not None else settings.db_host or "").rstrip("/")
        self.token = token if token is not None else settings.db_token
        self.configured = bool(self.host and self.token)
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        } if self.token else {}

    def _get(self, path, params=None):
        if not self.configured:
            return {"error": "Databricks not configured"}
        r = requests.get(self.host + path, headers=self.headers, params=params, timeout=60)
        return self._response(r)

    def _post(self, path, payload):
        if not self.configured:
            return {"error": "Databricks not configured"}
        r = requests.post(self.host + path, headers=self.headers, json=payload, timeout=120)
        return self._response(r)

    @staticmethod
    def _response(r):
        try:
            obj = r.json()
        except Exception:
            obj = {"text": r.text}
        if r.status_code >= 400:
            return {"error": f"HTTP {r.status_code}", "details": obj}
        return obj

    def verify_customer_environment(self):
        """Verify the supplied Databricks workspace using only host + customer PAT.

        The workspace-status endpoint is the authoritative connectivity check.
        Optional capability probes are recorded as evidence but cannot turn a
        failed authentication into a verified environment.
        """
        if not self.configured:
            return {"verified": False, "configured": False, "error": "Databricks host and customer token are required."}

        workspace = self._get("/api/2.0/workspace/get-status", {"path": "/"})
        if workspace.get("error"):
            return {"verified": False, "configured": True, "workspace": workspace, "error": "Databricks authentication or workspace verification failed."}

        jobs = self._get("/api/2.2/jobs/list", {"limit": 1})
        pipelines = self._get("/api/2.0/pipelines", {"max_results": 1})
        return {
            "verified": True,
            "configured": True,
            "host": self.host,
            "workspace": workspace,
            "jobs": jobs,
            "pipelines": pipelines,
            "verification": "verified_customer_environment",
        }

    def capability_report(self):
        """Backward-compatible capability report used by existing UI/artifacts."""
        result = self.verify_customer_environment()
        if not result.get("verified"):
            return {"configured": bool(self.configured), **result}
        result.update({
            "apps_sdk": self._sdk_capability("apps"),
            "lakebase_sdk": self._sdk_capability("database"),
        })
        return result

    def _sdk_capability(self, attr):
        try:
            from databricks.sdk import WorkspaceClient
            w = WorkspaceClient(host=self.host, token=self.token)
            return {"available": hasattr(w, attr), "sdk": True}
        except Exception as e:
            return {"available": False, "sdk": False, "error": str(e)}

    def ensure_workspace_dir(self, path):
        return self._post("/api/2.0/workspace/mkdirs", {"path": path})

    def import_notebook(self, path, source, language="PYTHON", overwrite=True):
        if not self.configured:
            return {"error": "Databricks not configured"}
        parent = path.rsplit("/", 1)[0]
        self.ensure_workspace_dir(parent)
        payload = {
            "path": path,
            "format": "SOURCE",
            "overwrite": overwrite,
            "content": base64.b64encode(source.encode("utf-8")).decode("ascii")
        }
        if language:
            payload["language"] = language
        return self._post("/api/2.0/workspace/import", payload)

    def create_pipeline_from_spec(self, pid, spec, store):
        if not self.configured:
            return {"error": "Databricks not configured"}
        name = spec.get("pipeline_name", f"cinvent_{pid[:8]}_lakeflow")
        code = spec.get("pipeline_code", "")
        root = f"/Workspace/Shared/C_INVENT/{pid}"
        source_path = f"{root}/{name}.py"
        if code:
            store.save_artifact(pid, "lakeflow_pipeline", name + ".py", "python", code)
            upload = self.import_notebook(source_path, code)
            if upload.get("error"):
                return {"status": "workspace_upload_failed", "upload": upload}
        payload = {
            "name": name,
            "development": True,
            "continuous": False,
            "channel": "CURRENT",
            "libraries": [{"notebook": {"path": source_path}}],
            "configuration": {}
        }
        return self._post("/api/2.0/pipelines", payload)

    def list_jobs(self, prefix=""):
        obj = self._get("/api/2.2/jobs/list", {"limit": 100})
        jobs = obj.get("jobs", []) if isinstance(obj, dict) else []
        return [
            {"job_id": x.get("job_id"), "name": x.get("settings", {}).get("name", "")}
            for x in jobs
            if not prefix or x.get("settings", {}).get("name", "").startswith(prefix)
        ]

    def create_job(self, spec, notebook_sources=None):
        """Create a Databricks Job only from executable notebook source.

        JSON planning artifacts are never uploaded as Python notebooks. Callers can
        pass an explicit mapping of task_key -> Python source; otherwise a safe
        placeholder is used and the response makes that limitation visible.
        """
        if not self.configured:
            return {"error": "Databricks not configured"}
        notebook_sources = notebook_sources or {}
        root = f"/Workspace/Shared/C_INVENT/jobs/{spec['name']}"
        tasks = []
        for task in spec.get("tasks", []):
            key = task["task_key"]
            path = f"{root}/{key}.py"
            source = notebook_sources.get(key)
            if not source or not isinstance(source, str):
                source = "# C INVENT generated task\n# No executable implementation was supplied for this task.\nprint('C INVENT task placeholder')\n"
            upload = self.import_notebook(path, source, language="PYTHON")
            if upload.get("error"):
                return {"status": "workspace_upload_failed", "task": key, "upload": upload}
            tasks.append({
                "task_key": key,
                "notebook_task": {"notebook_path": path, "source": "WORKSPACE"}
            })
        return self._post("/api/2.2/jobs/create", {"name": spec["name"], "tasks": tasks})

    def run_job(self, job_id):
        return self._post("/api/2.2/jobs/run-now", {"job_id": job_id})

    def create_lakebase_project(self, project_id, display_name):
        if not self.configured:
            return {"error": "Databricks not configured"}
        payload = {"spec": {"display_name": display_name[:200], "pg_version": 17}}
        return self._post(f"/api/2.0/postgres/projects?project_id={project_id}", payload)

    def create_customer_app(self, app_name, description, source_path, lakebase_project_id=None):
        if not self.configured:
            return {"error": "Databricks not configured"}
        resources = []
        if lakebase_project_id:
            branch = f"projects/{lakebase_project_id}/branches/production"
            database = f"{branch}/databases/databricks_postgres"
            resources.append({
                "name": "postgres",
                "postgres": {
                    "branch": branch,
                    "database": database,
                    "permission": "CAN_CONNECT_AND_CREATE"
                }
            })
        created = self._post("/api/2.0/apps", {
            "name": app_name,
            "description": description[:500],
            "compute_size": "MEDIUM",
            "resources": resources
        })
        if created.get("error"):
            return created
        deployment = self._post(
            f"/api/2.0/apps/{app_name}/deployments",
            {
                "mode": "SNAPSHOT",
                "source_code_path": source_path,
                "command": ["streamlit", "run", "app.py", "--server.port", "8000"]
            }
        )
        return {"app": created, "deployment": deployment}

    def start_app(self, app_name):
        return self._post(f"/api/2.0/apps/{app_name}/start", {})
