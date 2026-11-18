from dataclasses import dataclass

from evidence.coordinates import compile_coefficients, named_coefficients, require_integer


@dataclass(frozen=True)
class Observation:
    coefficients: tuple[int, ...]
    rhs: int
    modulus: int | None = None


def normalize_observation(frame, data):
    if type(data) is not dict or data.keys() not in (
        {'coefficients', 'rhs'}, {'coefficients', 'rhs', 'modulus'},
    ):
        raise ValueError('observation requires coefficients and rhs, with an optional modulus')
    coefficients = compile_coefficients(frame, data['coefficients'])
    rhs = require_integer(data['rhs'], 'observation rhs')
    modulus = None
    if 'modulus' in data:
        modulus = require_integer(data['modulus'], 'modulus')
        if modulus <= 0:
            raise ValueError('modulus must be positive')
    return Observation(coefficients, rhs, modulus)


def encode_observation(frame, observation):
    data = {'coefficients': named_coefficients(frame, observation.coefficients), 'rhs': observation.rhs}
    if observation.modulus is not None:
        data['modulus'] = observation.modulus
    return data


def decode_observation(frame, data):
    return normalize_observation(frame, data)
