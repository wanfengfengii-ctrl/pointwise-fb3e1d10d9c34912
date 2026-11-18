from archive.payloads import decode_payload, encode_payload


def install_review_schema(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS review_requests (
            request_id TEXT PRIMARY KEY NOT NULL,
            calibration_id TEXT NOT NULL,
            expressions BLOB NOT NULL
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS review_submissions (
            request_id TEXT NOT NULL REFERENCES review_requests(request_id),
            side TEXT NOT NULL CHECK (side IN ('left', 'right')),
            version BLOB NOT NULL,
            claim BLOB NOT NULL,
            PRIMARY KEY(request_id, side, version)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS review_withdrawals (
            request_id TEXT NOT NULL,
            side TEXT NOT NULL CHECK (side IN ('left', 'right')),
            version BLOB NOT NULL,
            PRIMARY KEY(request_id, side, version)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS review_receipts (
            request_id TEXT NOT NULL,
            left_version BLOB NOT NULL,
            right_version BLOB NOT NULL,
            report_id TEXT NOT NULL,
            PRIMARY KEY(request_id, left_version, right_version)
        )
    ''')


def insert_request_row(connection, request_id, calibration_id, expressions):
    connection.execute('''
        INSERT INTO review_requests(request_id, calibration_id, expressions)
        VALUES (?, ?, ?)
    ''', (request_id, calibration_id, encode_payload(expressions)))


def get_request_row(connection, request_id):
    return connection.execute('''
        SELECT calibration_id, expressions FROM review_requests WHERE request_id = ?
    ''', (request_id,)).fetchone()


def get_submission_row(connection, request_id, side, version):
    return connection.execute('''
        SELECT claim FROM review_submissions
        WHERE request_id = ? AND side = ? AND version = ?
    ''', (request_id, side, encode_payload(version))).fetchone()


def insert_submission_row(connection, request_id, side, version, claim):
    connection.execute('''
        INSERT INTO review_submissions(request_id, side, version, claim)
        VALUES (?, ?, ?, ?)
    ''', (request_id, side, encode_payload(version), encode_payload(claim)))


def has_withdrawal_row(connection, request_id, side, version):
    return connection.execute('''
        SELECT 1 FROM review_withdrawals
        WHERE request_id = ? AND side = ? AND version = ?
    ''', (request_id, side, encode_payload(version))).fetchone() is not None


def insert_withdrawal_row(connection, request_id, side, version):
    connection.execute('''
        INSERT OR IGNORE INTO review_withdrawals(request_id, side, version)
        VALUES (?, ?, ?)
    ''', (request_id, side, encode_payload(version)))


def get_receipt_row(connection, request_id, left_version, right_version):
    return connection.execute('''
        SELECT report_id FROM review_receipts
        WHERE request_id = ? AND left_version = ? AND right_version = ?
    ''', (request_id, encode_payload(left_version), encode_payload(right_version))).fetchone()


def insert_receipt_row(connection, request_id, left_version, right_version, report_id):
    connection.execute('''
        INSERT INTO review_receipts(request_id, left_version, right_version, report_id)
        VALUES (?, ?, ?, ?)
    ''', (request_id, encode_payload(left_version),
          encode_payload(right_version), report_id))


def request_expressions(row):
    return decode_payload(row[1])


def submission_claim(row):
    return decode_payload(row[0])
