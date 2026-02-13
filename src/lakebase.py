from databricks.sdk import WorkspaceClient
import psycopg
from psycopg_pool import ConnectionPool
from uuid import uuid4


class LakebaseConnect:
    """A class to manage database connections to Lakebase Autoscaling.

    Uses the w.postgres API with hierarchical resource names:
      projects/{project_id}/branches/{branch_id}/endpoints/{endpoint_id}

    OAuth tokens are generated via w.postgres.generate_database_credential()
    and expire after 1 hour. The connection pool uses a custom connection class
    to auto-refresh tokens on each new connection from the pool.
    """

    def __init__(
        self,
        user: str,
        instance_name: str = None,
        project_id: str = None,
        branch_id: str = None,
        endpoint_id: str = None,
        database: str = "databricks_postgres",
        password: str = None,
        port: int = 5432,
        wsClient: WorkspaceClient = WorkspaceClient(),
    ):
        """
        Initialize the Lakebase Autoscaling connection.

        Args:
            user: Postgres role (typically SP client_id or user email)
            project_id: Lakebase project ID
            branch_id: Lakebase branch ID (default: "main")
            endpoint_id: Lakebase endpoint ID (default: "primary")
            database: Database name (default: "databricks_postgres")
            password: Pre-existing password/token (optional; auto-generated if None)
            port: Port number for the connection (default: 5432)
            wsClient: Authenticated WorkspaceClient instance
        """
        self.instance_name = instance_name
        self.endpoint_id = endpoint_id
        self.project_id = project_id
        self.branch_id = branch_id
        self.database = database
        self.port = port
        self.user = user
        self.password = password
        self.connection_pool = None
        self.url = None
        self.w = wsClient

        print(
            f"WorkspaceClient initialized with user {self.w.current_user.me().user_name}"
        )

        if self.instance_name and self.endpoint_id:
            print(f"instance_name {self.instance_name} and endpoint_id {self.endpoint_id} cannot be both specified at the same time. Connect by either instance_name or endpoint_name, not both. To connect with both, initialize LakebaseConnect again")

        if self.endpoint_id:
            if not self.project_id or not self.branch_id:
                raise ValueError(
                    "endpoint_id requires project_id and branch_id to also be specified"
                )
        
        if self.instance_name:
            instance = self.w.database.get_database_instance(name=self.instance_name)
            self.host = instance.read_write_dns
            print(f"Lakebase instance: {self.instance_name} -> {self.host}")

        if self.endpoint_id and self.project_id and self.branch_id:
            self.endpoint_name = (
                f"projects/{project_id}/branches/{branch_id}/endpoints/{endpoint_id}"
            )
            # Resolve endpoint host via Lakebase Autoscaling API
            endpoint = self.w.postgres.get_endpoint(name=self.endpoint_name)
            self.host = endpoint.status.hosts.host
            print(f"Lakebase endpoint: {self.endpoint_name} -> {self.host}")

    def _generate_token(self) -> str:
        """Generate an ephemeral OAuth token (1h expiry) for the endpoint."""
        cred = None
        if self.instance_name:
            cred = self.w.database.generate_database_credential(
                request_id=str(uuid4()), instance_names=[self.instance_name]
            )
        if self.endpoint_id:
            cred = self.w.postgres.generate_database_credential(
                endpoint=self.endpoint_name
            )
        return cred

    def _connect(self):
        """Set up the database connection with token auto-refresh via connection pool.

        Uses a custom psycopg Connection class that generates a fresh OAuth token
        for each new connection from the pool, ensuring tokens never expire mid-session.
        """
        if self.password is None:
            self.password = self._generate_token().token

        self.url = f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}?sslmode=require"
        self.conninfo = f"dbname={self.database} user={self.user} password={self.password} host={self.host} sslmode=require"

        # Build a custom connection class that auto-refreshes tokens
        lakebase_ref = self  # capture reference for closure

        class AutoRefreshConnection(psycopg.Connection):
            @classmethod
            def connect(cls, conninfo=lakebase_ref.conninfo, **kwargs):
                # Generate a fresh OAuth token for each new connection
                kwargs["password"] = lakebase_ref._generate_token()
                return super().connect(conninfo, **kwargs)

        self.connection_pool = ConnectionPool(
            conninfo=self.conninfo,
#            connection_class=AutoRefreshConnection,
            kwargs={"autocommit": True},
            min_size=1,
            max_size=10,
            open=True,
        )

    def query(self, query: str):
        """
        Execute a SQL query against the database.

        Args:
            query: SQL query string to execute

        Returns:
            Query result
        """
        if self.connection_pool is None:
            raise RuntimeError(
                "Database connection not initialized. Call _connect() first."
            )

        with self.connection_pool.connection() as conn:
            result = conn.execute(query)
            return result.fetchall()

    def close(self):
        """Close the database connection."""
        if self.connection_pool:
            self.connection_pool.close()
            self.connection_pool = None

    def test_query(self):
        query = "SELECT version()"
        self._connect()
        try:
            result = self.query(query)
            print(f"Successfully queried Lakebase with result: {result}")
            return result
        except Exception as e:
            print(f"Error: {e}")
        finally:
            self.close()