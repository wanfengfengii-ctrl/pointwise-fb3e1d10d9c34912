from dataclasses import dataclass
from math import gcd

from archive.payloads import require_object
from calibration.integer_relation import evaluate_linear_form


@dataclass(frozen=True)
class ResidueClass:
    residue: int
    step: int

    def __post_init__(self):
        if type(self.residue) is not int or type(self.step) is not int:
            raise ValueError('residue and step must be integers')
        if not 0 <= self.residue < self.step:
            raise ValueError('invalid residue or step')


def project_channel(relation, coefficients):
    base, directions = evaluate_linear_form(relation, coefficients)
    step = gcd(*directions)
    return ResidueClass(base % step, step) if step else base


def encode_value_set(value_set):
    if isinstance(value_set, ResidueClass):
        return {'residue': value_set.residue, 'step': value_set.step}
    if type(value_set) is int:
        return value_set
    raise ValueError('invalid value set')


def decode_value_set(data):
    if type(data) is int:
        return data
    fields = require_object(data, 'residue', 'step')
    return ResidueClass(fields['residue'], fields['step'])
