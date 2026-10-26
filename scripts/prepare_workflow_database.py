"""Create the isolated browser database; never mutate live records."""
import os
import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

url = make_url(os.environ["CENTRAL_DATABASE_URL"])
target = url.database + "_workflow_ui_test"
assert target.endswith("_workflow_ui_test")
with psycopg.connect(host=url.host, port=url.port or 5432, user=url.username, password=url.password,
                     dbname="postgres", autocommit=True) as connection:
    if not connection.execute("SELECT 1 FROM pg_database WHERE datname=%s", (target,)).fetchone():
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
print("Isolated workflow database ready")
