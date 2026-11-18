from dataclasses import dataclass

from archive.database import write_transaction
from archive.payloads import decode_payload, encode_payload, require_list, require_object
from evidence.batches import Batch, check_batch_compatibility, decode_batch, encode_batch, validate_batch
from evidence.coordinates import require_text
from evidence.observations import Observation, decode_observation, encode_observation, normalize_observation
from evidence.storage import get_batch_row, get_revision_row, insert_batch_row, insert_revision_row


class BatchNotFound(LookupError):
    pass


class RevisionNotFound(LookupError):
    pass


class RevisionConflict(ValueError):
    pass


@dataclass(frozen=True)
class EvidenceRef:
    batch_id: str
    evidence_id: str
    revision: str

    def __post_init__(self):
        require_text(self.batch_id, 'batch ID')
        require_text(self.evidence_id, 'evidence ID')
        require_text(self.revision, 'revision ID')

    def key(self):
        return self.batch_id, self.evidence_id, self.revision


@dataclass(frozen=True)
class EvidenceRevision:
    batch: Batch
    ref: EvidenceRef
    observations: tuple[Observation, ...]


def _batch_from_row(batch_id, row):
    unit, coordinates = row
    return Batch(batch_id, unit, require_list(decode_payload(coordinates)))


def load_batch(connection, batch_id):
    require_text(batch_id, 'batch ID')
    row = get_batch_row(connection, batch_id)
    if row is None:
        raise BatchNotFound(batch_id)
    return _batch_from_row(batch_id, row)


def record(connection, batch, evidence_id, revision, observations):
    batch = validate_batch(batch)
    ref = EvidenceRef(batch.batch_id, evidence_id, revision)
    if type(observations) not in (list, tuple):
        raise ValueError('observations must be an ordered sequence')
    frame = batch.frame
    normalized = tuple(normalize_observation(frame, item) for item in observations)
    content = encode_payload([encode_observation(frame, item) for item in normalized])
    with write_transaction(connection):
        batch_row = get_batch_row(connection, batch.batch_id)
        if batch_row is None:
            insert_batch_row(connection, batch.batch_id, batch.unit, encode_payload(batch.coordinates))
        else:
            check_batch_compatibility(_batch_from_row(batch.batch_id, batch_row), batch)
        saved = get_revision_row(connection, *ref.key())
        if saved is None:
            insert_revision_row(connection, *ref.key(), content)
        elif saved[0] != content:
            raise RevisionConflict(f'different content already registered for {ref!r}')
    return ref


def _decode_observations(batch, data):
    frame = batch.frame
    return tuple(decode_observation(frame, item) for item in require_list(data))


def fetch_revision(connection, ref):
    if not isinstance(ref, EvidenceRef):
        raise ValueError('expected an exact EvidenceRef')
    row = get_revision_row(connection, *ref.key())
    if row is None:
        raise RevisionNotFound(ref)
    batch = load_batch(connection, ref.batch_id)
    return EvidenceRevision(batch, ref, _decode_observations(batch, decode_payload(row[0])))


def encode_ref(ref):
    return {'batch_id': ref.batch_id, 'evidence_id': ref.evidence_id, 'revision': ref.revision}


def decode_ref(data):
    fields = require_object(data, 'batch_id', 'evidence_id', 'revision')
    return EvidenceRef(fields['batch_id'], fields['evidence_id'], fields['revision'])


def encode_revision(revision):
    frame = revision.batch.frame
    return {'batch': encode_batch(revision.batch), 'ref': encode_ref(revision.ref),
            'observations': [encode_observation(frame, item) for item in revision.observations]}


def decode_revision(data):
    fields = require_object(data, 'batch', 'ref', 'observations')
    batch, ref = decode_batch(fields['batch']), decode_ref(fields['ref'])
    if batch.batch_id != ref.batch_id:
        raise ValueError('revision and batch identities differ')
    return EvidenceRevision(batch, ref, _decode_observations(batch, fields['observations']))
