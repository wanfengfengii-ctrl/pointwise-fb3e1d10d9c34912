from enum import StrEnum
from uuid import uuid4

from archive.database import write_transaction
from evidence.storage import install_evidence_schema


class ArtifactKind(StrEnum):
    CALIBRATION = 'calibration'
    REPORT = 'report'


def initialize_store(connection):
    with write_transaction(connection):
        install_evidence_schema(connection)
        connection.execute('''
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY NOT NULL,
                kind TEXT NOT NULL,
                parent_id TEXT REFERENCES artifacts(id),
                payload BLOB NOT NULL,
                CHECK ((kind = 'calibration' AND parent_id IS NULL)
                    OR (kind = 'report' AND parent_id IS NOT NULL))
            )
        ''')
        connection.execute('CREATE INDEX IF NOT EXISTS artifacts_by_kind ON artifacts(kind, id)')


def allocate_artifact_id():
    return uuid4().hex


def get_catalog_entry(connection, artifact_id):
    return connection.execute(
        'SELECT kind, id, parent_id, payload FROM artifacts WHERE id = ?', (artifact_id,),
    ).fetchone()


def insert_catalog_entry(connection, artifact):
    connection.execute(
        'INSERT INTO artifacts(kind, id, parent_id, payload) VALUES (?, ?, ?, ?)',
        (artifact.kind, artifact.artifact_id, artifact.parent_id, artifact.payload),
    )


def list_artifacts(connection, kind):
    return tuple(row[0] for row in connection.execute(
        'SELECT id FROM artifacts WHERE kind = ? ORDER BY id', (ArtifactKind(kind),),
    ))
