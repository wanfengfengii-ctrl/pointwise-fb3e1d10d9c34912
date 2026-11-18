def install_evidence_schema(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS batches (
            id TEXT PRIMARY KEY NOT NULL,
            unit TEXT NOT NULL,
            coordinates BLOB NOT NULL
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS evidence_revisions (
            batch_id TEXT NOT NULL REFERENCES batches(id),
            evidence_id TEXT NOT NULL,
            revision TEXT NOT NULL,
            observations BLOB NOT NULL,
            PRIMARY KEY(batch_id, evidence_id, revision)
        )
    ''')


def get_batch_row(connection, batch_id):
    return connection.execute(
        'SELECT unit, coordinates FROM batches WHERE id = ?', (batch_id,),
    ).fetchone()


def insert_batch_row(connection, batch_id, unit, coordinates):
    connection.execute(
        'INSERT INTO batches(id, unit, coordinates) VALUES (?, ?, ?)', (batch_id, unit, coordinates),
    )


def get_revision_row(connection, batch_id, evidence_id, revision):
    return connection.execute('''
        SELECT observations FROM evidence_revisions
        WHERE batch_id = ? AND evidence_id = ? AND revision = ?
    ''', (batch_id, evidence_id, revision)).fetchone()


def insert_revision_row(connection, batch_id, evidence_id, revision, observations):
    connection.execute('''
        INSERT INTO evidence_revisions(batch_id, evidence_id, revision, observations)
        VALUES (?, ?, ?, ?)
    ''', (batch_id, evidence_id, revision, observations))
