"""Run inside a release backend against a restored, explicitly test-only database."""
import hashlib
import json
import os
import subprocess
from urllib.parse import urlsplit
import psycopg
from psycopg import sql

dsn = os.environ['CENTRAL_DATABASE_URL'].replace('postgresql+psycopg://', 'postgresql://')
assert urlsplit(dsn).path.endswith('_test'), 'Refusing migration rehearsal outside a test database'


def digest(connection, table, columns):
    rows = connection.execute(sql.SQL('SELECT {} FROM {}').format(
        sql.SQL(',').join(map(sql.Identifier, columns)), sql.Identifier(table))).fetchall()
    encoded = sorted(json.dumps(row, default=str, ensure_ascii=False) for row in rows)
    return {'rows': len(rows), 'sha256': hashlib.sha256('\n'.join(encoded).encode()).hexdigest()}


with psycopg.connect(dsn) as connection:
    columns = {}
    for table, column in connection.execute("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name,ordinal_position"):
        if table != 'alembic_version':
            columns.setdefault(table, []).append(column)
    before = {table: digest(connection, table, names) for table, names in columns.items()}
subprocess.run(['alembic', 'upgrade', 'head'], check=True)
with psycopg.connect(dsn) as connection:
    after = {table: digest(connection, table, names) for table, names in columns.items()}
    head = connection.execute('SELECT version_num FROM alembic_version').fetchone()[0]
assert before == after, 'Migration altered pre-existing column values or rows'
assert head == 'f165789dab45', head
print(json.dumps({'head': head, 'unchanged_existing_tables': before, 'result': 'PASS'}, indent=2), flush=True)
