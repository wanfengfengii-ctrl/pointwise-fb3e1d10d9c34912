import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from archive.catalog import get_catalog_entry, initialize_store
from archive.database import open_database
from calibration.admission import admit_constraints, calibrate
from calibration.congruences import apply_congruence
from calibration.equations import apply_equation
from evidence.batches import Batch
from evidence.revisions import record
from review.joint import evaluate_joint_claim
from review.projection import project_channel
from review.reports import assess


BATCH = Batch('line-a', 'tick', ('x', 'y'))
XY = ({'x': 1}, {'y': 1})


def equation(coefficients, rhs):
    return {'coefficients': coefficients, 'rhs': rhs}


def congruence(coefficients, rhs, modulus):
    return {'coefficients': coefficients, 'rhs': rhs, 'modulus': modulus}


class StoreTestCase(TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.path = Path(directory) / 'store.sqlite3'
        self.db = self.connect()
        initialize_store(self.db)

    def connect(self):
        db = open_database(self.path)
        self.addCleanup(db.close)
        return db

    def reopen(self):
        self.db.close()
        self.db = self.connect()

    def marks(self, observations, revision='1', evidence_id='bench'):
        return record(self.db, BATCH, evidence_id, revision, observations)

    def parity(self, modulus=2, rhs=0, revision='1'):
        ref = self.marks([congruence({'x': 1, 'y': 1}, rhs, modulus)], revision)
        return ref, calibrate(self.db, BATCH.batch_id, [ref])

    def exact(self):
        ref = self.marks([equation({'x': 1}, 2), equation({'y': 1}, -1)])
        return ref, calibrate(self.db, BATCH.batch_id, [ref])


class FailBeforeCommit:
    def __init__(self, observer):
        self.observer = observer
        self.artifact_id = None
        self.pending = None
        self.visible = None

    def __call__(self, connection, artifact_id):
        self.artifact_id = artifact_id
        self.pending = get_catalog_entry(connection, artifact_id)
        self.visible = get_catalog_entry(self.observer, artifact_id)
        # A real duplicate-key write fails after the candidate row has been staged.
        connection.execute('''
            INSERT INTO artifacts(kind, id, parent_id, payload)
            SELECT kind, id, parent_id, payload FROM artifacts WHERE id = ?
        ''', (artifact_id,))


@contextmanager
def analysis_disabled():
    blocked = {function.__code__ for function in (
        calibrate, admit_constraints, apply_congruence, apply_equation,
        assess, project_channel, evaluate_joint_claim,
    )}

    def guard(frame, event, arg):
        if event == 'call' and frame.f_code in blocked:
            raise RuntimeError('analysis entry is disabled')

    previous = sys.getprofile()
    sys.setprofile(guard)
    try:
        yield
    finally:
        sys.setprofile(previous)
