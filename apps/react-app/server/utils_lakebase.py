"""
Lakebase Autoscaling Postgres database layer for the AiChemy web server.

Persists project metadata (name, timestamps, user), chat messages,
and parsed agent steps (tool calls, genie results).
"""

import json
from uuid import uuid4
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Optional
from databricks.sdk import WorkspaceClient
from agent.utils import get_secret_from_cfg, load_config


class ProjectDB:
    """Project metadata persisted to Lakebase Autoscaling Postgres.

    Lakebase Autoscaling uses the w.postgres API with hierarchical resource names:
      projects/{project_id}/branches/{branch_id}/endpoints/{endpoint_id}
    """

    def __init__(self):
        self._last_lakebase_error: Optional[str] = None
        self._sp_client: Optional[WorkspaceClient] = None
        self._lakebase_project_id: Optional[str] = None
        self._lakebase_branch_id: Optional[str] = None
        self._lakebase_endpoint_id: Optional[str] = None
        self._lakebase_database: Optional[str] = None
        self._lakebase_endpoint_name: Optional[str] = None
        self._lakebase_host: Optional[str] = None
        self._lakebase_token: Optional[str] = None
        self._lakebase_user: Optional[str] = None
        self._token_issued_at: float = 0.0

        try:
            cfg = load_config()
            if not cfg:
                raise RuntimeError("config.yml not found")

            lakebase_cfg = cfg.get("lakebase")
            if not lakebase_cfg or not lakebase_cfg.get("project_id"):
                raise RuntimeError("lakebase config missing project_id")

            self._lakebase_project_id = lakebase_cfg["project_id"]
            self._lakebase_branch_id = lakebase_cfg.get("branch_id", "main")
            self._lakebase_endpoint_id = lakebase_cfg.get("endpoint_id", "primary")
            self._lakebase_database = lakebase_cfg.get("database", "databricks_postgres")
            self._lakebase_endpoint_name = (
                f"projects/{self._lakebase_project_id}"
                f"/branches/{self._lakebase_branch_id}"
                f"/endpoints/{self._lakebase_endpoint_id}"
            )
            self._host = cfg.get("host")

            sp_client_id, sp_client_secret = get_secret_from_cfg(cfg)
            if not (sp_client_id and sp_client_secret):
                raise RuntimeError("SP credentials not found in secrets")

            self._sp_client = WorkspaceClient(
                host=self._host,
                client_id=sp_client_id,
                client_secret=sp_client_secret,
            )

            endpoint = self._sp_client.postgres.get_endpoint(
                name=self._lakebase_endpoint_name
            )
            self._lakebase_host = endpoint.status.hosts.host
            self._lakebase_user = sp_client_id

            self._refresh_token()
            self._connect_with_retry(self._build_conninfo())
            self._ensure_schema()
            print(f"[ProjectDB] Connected: {self._lakebase_host} / {self._lakebase_database}")

        except Exception:
            import traceback
            self._last_lakebase_error = traceback.format_exc()
            print(f"[ProjectDB] Lakebase connection failed:\n{self._last_lakebase_error}")
            raise

    def _build_conninfo(self) -> str:
        return (
            f"dbname={self._lakebase_database} "
            f"user={self._lakebase_user} "
            f"password={self._lakebase_token} "
            f"host={self._lakebase_host} "
            f"sslmode=require"
        )

    def _connect_with_retry(self, conninfo: str, max_retries: int = 5, base_delay: float = 1.0):
        """Retry connection for Lakebase scale-to-zero wake-up."""
        import psycopg
        import time

        last_error = None
        for attempt in range(max_retries):
            try:
                with psycopg.connect(conninfo, connect_timeout=10) as conn:
                    conn.execute("SELECT 1")
                return
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    print(f"[ProjectDB] Attempt {attempt + 1} failed, retrying in {delay}s... ({e})")
                    time.sleep(delay)
        raise last_error

    def _refresh_token(self):
        """Refresh the Lakebase OAuth token using the cached SP client."""
        import time

        cred = self._sp_client.postgres.generate_database_credential(
            endpoint=self._lakebase_endpoint_name,
        )
        self._lakebase_token = cred.token
        self._token_issued_at = time.monotonic()
        print("[ProjectDB] Token refreshed")

    def _ensure_schema(self):
        """Create the projects table if it doesn't exist; migrate if needed."""
        import psycopg

        with psycopg.connect(self._build_conninfo(), connect_timeout=10) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'projects'
                )
            """)
            if cur.fetchone()[0]:
                print("[ProjectDB] projects table already exists")
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'projects'
                """)
                existing_cols = {row[0] for row in cur.fetchall()}
                try:
                    if "messages" not in existing_cols:
                        cur.execute("ALTER TABLE projects ADD COLUMN messages TEXT NOT NULL DEFAULT '[]'")
                        print("[ProjectDB] Added messages column")
                    if "trace_ids" in existing_cols:
                        cur.execute("ALTER TABLE projects DROP COLUMN trace_ids")
                        print("[ProjectDB] Dropped trace_ids column")
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    print(f"[ProjectDB] Schema migration skipped (not owner?): {e}")
                return
            cur.execute("""
                CREATE TABLE projects (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    messages TEXT NOT NULL DEFAULT '[]',
                    agent_steps TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id)")
            conn.commit()

    _TOKEN_LIFETIME = 3000

    @contextmanager
    def _conn(self):
        """Yield a Postgres connection, proactively refreshing the token before expiry."""
        import psycopg
        import time

        if time.monotonic() - self._token_issued_at > self._TOKEN_LIFETIME:
            try:
                self._refresh_token()
            except Exception as e:
                print(f"[ProjectDB] Proactive token refresh failed: {e}")
        try:
            with psycopg.connect(self._build_conninfo(), connect_timeout=10) as conn:
                yield conn
        except psycopg.OperationalError as e:
            print(f"[ProjectDB] Connection failed ({e}), refreshing token...")
            self._refresh_token()
            self._connect_with_retry(self._build_conninfo(), max_retries=3, base_delay=0.5)
            with psycopg.connect(self._build_conninfo(), connect_timeout=10) as conn:
                yield conn

    # -- CRUD ---------------------------------------------------------------

    def list_projects(self, user_id: str) -> list[dict]:
        with self._conn() as conn:
            import psycopg.rows
            cur = conn.cursor(row_factory=psycopg.rows.dict_row)
            cur.execute(
                "SELECT id, name, created_at, updated_at FROM projects "
                "WHERE user_id = %s ORDER BY updated_at DESC",
                (user_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def create_project(self, user_id: str, name: str) -> dict:
        project_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.cursor().execute(
                "INSERT INTO projects (id, user_id, name, messages, agent_steps, created_at, updated_at) "
                "VALUES (%s, %s, %s, '[]', '{}', %s, %s)",
                (project_id, user_id, name, now, now),
            )
            conn.commit()
        return {
            "id": project_id, "name": name, "messages": [], "agent_steps": {},
            "created_at": now, "updated_at": now,
        }

    def get_project(self, project_id: str) -> Optional[dict]:
        with self._conn() as conn:
            import psycopg.rows
            cur = conn.cursor(row_factory=psycopg.rows.dict_row)
            cur.execute("SELECT * FROM projects WHERE id = %s", (project_id,))
            row = cur.fetchone()
            if row is None:
                return None
            d = dict(row)
            d.pop("user_id", None)
            d["messages"] = json.loads(d.get("messages", "[]"))
            d["agent_steps"] = json.loads(d.get("agent_steps", "{}"))
            return d

    def update_project(self, project_id: str, name: Optional[str] = None,
                       messages: Optional[list] = None, agent_steps=None) -> Optional[dict]:
        with self._conn() as conn:
            import psycopg.rows
            cur = conn.cursor(row_factory=psycopg.rows.dict_row)
            cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
            if cur.fetchone() is None:
                return None
            now = datetime.now(timezone.utc).isoformat()
            updates = ["updated_at = %s"]
            params: list = [now]
            if name is not None:
                updates.append("name = %s")
                params.append(name)
            if messages is not None:
                updates.append("messages = %s")
                params.append(json.dumps(messages))
            if agent_steps is not None:
                updates.append("agent_steps = %s")
                params.append(json.dumps(agent_steps))
            params.append(project_id)
            cur.execute(f"UPDATE projects SET {', '.join(updates)} WHERE id = %s", params)
            conn.commit()
        return self.get_project(project_id)

    def delete_project(self, project_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
            deleted = cur.rowcount > 0
            conn.commit()
            return deleted
