from dataclasses import dataclass

from archive.payloads import require_list, require_object
from calibration.integer_relation import IntegerRelation
from evidence.batches import Batch, decode_batch, encode_batch
from evidence.revisions import EvidenceRef, decode_ref, encode_ref


@dataclass(frozen=True)
class FixedCalibration:
    batch: Batch
    evidence_refs: tuple[EvidenceRef, ...]
    relation: IntegerRelation

    def __post_init__(self):
        if len(self.relation.point) != len(self.batch.coordinates):
            raise ValueError('fixed relation and batch have different dimensions')
        if any(ref.batch_id != self.batch.batch_id for ref in self.evidence_refs):
            raise ValueError('fixed selection contains another batch')


def encode_calibration(calibration):
    return {
        'batch': encode_batch(calibration.batch),
        'evidence': [encode_ref(ref) for ref in calibration.evidence_refs],
        'point': list(calibration.relation.point),
        'directions': [list(direction) for direction in calibration.relation.directions],
    }


def decode_calibration(data):
    fields = require_object(data, 'batch', 'evidence', 'point', 'directions')
    batch = decode_batch(fields['batch'])
    refs = tuple(decode_ref(ref) for ref in require_list(fields['evidence']))
    point = tuple(require_list(fields['point']))
    directions = tuple(tuple(require_list(row)) for row in require_list(fields['directions']))
    return FixedCalibration(batch, refs, IntegerRelation(point, directions))
