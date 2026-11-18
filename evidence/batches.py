from dataclasses import dataclass

from archive.payloads import require_list, require_object
from evidence.coordinates import CoordinateFrame, normalize_coordinates, require_text


class BatchConflict(ValueError):
    pass


@dataclass(frozen=True)
class Batch:
    batch_id: str
    unit: str
    coordinates: tuple[str, ...]

    def __post_init__(self):
        require_text(self.batch_id, 'batch ID')
        require_text(self.unit, 'tick unit')
        object.__setattr__(self, 'coordinates', normalize_coordinates(self.coordinates))

    @property
    def frame(self):
        return CoordinateFrame(self.coordinates)


def validate_batch(batch):
    if not isinstance(batch, Batch):
        raise ValueError('expected a Batch')
    return batch


def check_batch_compatibility(saved, incoming):
    if saved != incoming:
        raise BatchConflict('batch identity, tick unit and coordinate order must match')


def encode_batch(batch):
    return {'batch_id': batch.batch_id, 'unit': batch.unit, 'coordinates': list(batch.coordinates)}


def decode_batch(data):
    fields = require_object(data, 'batch_id', 'unit', 'coordinates')
    return Batch(fields['batch_id'], fields['unit'], require_list(fields['coordinates']))
