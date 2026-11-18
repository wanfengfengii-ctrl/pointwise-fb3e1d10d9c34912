import base64
import json
from dataclasses import dataclass


def require_object(value, *fields):
    if type(value) is not dict or value.keys() != set(fields):
        raise ValueError('unexpected object fields')
    return value


def require_list(value):
    if type(value) is not list:
        raise ValueError('expected a JSON array')
    return value


def _decimal(value):
    try:
        return str(value)
    except ValueError:
        number = abs(value)
        chunks = []
        while number >= 10**9:
            number, chunk = divmod(number, 10**9)
            chunks.append(chunk)
        sign = '-' if value < 0 else ''
        return sign + str(number) + ''.join(f'{chunk:09d}' for chunk in reversed(chunks))


def _parse_integer(text):
    try:
        return int(text)
    except ValueError:
        digits = text.removeprefix('-')
        value = 0
        for start in range(0, len(digits), 9):
            chunk = digits[start:start + 9]
            value = value * 10**len(chunk) + int(chunk)
        return -value if text.startswith('-') else value


def _encode(value):
    if type(value) is int:
        return _decimal(value)
    if value is None or type(value) in (bool, str):
        return json.dumps(value, ensure_ascii=True)
    if type(value) in (list, tuple):
        return '[' + ','.join(_encode(item) for item in value) + ']'
    if type(value) is dict and all(type(key) is str for key in value):
        return '{' + ','.join(_encode(key) + ':' + _encode(value[key]) for key in sorted(value)) + '}'
    raise ValueError('payload requires JSON objects, arrays, text, integers, booleans or null')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON field')
        result[key] = value
    return result


def _reject_noninteger(token):
    raise ValueError(f'invalid numeric token {token}')


def encode_payload(value):
    return _encode(value).encode('ascii')


def decode_payload(data):
    return json.loads(data.decode('utf-8'), object_pairs_hook=_unique_object,
                      parse_int=_parse_integer, parse_float=_reject_noninteger,
                      parse_constant=_reject_noninteger)


def encode_bytes(data):
    return base64.b64encode(data).decode('ascii')


def decode_bytes(text):
    if type(text) is not str:
        raise ValueError('expected base64 text')
    return base64.b64decode(text, validate=True)


@dataclass(frozen=True)
class ArtifactEnvelope:
    kind: str
    artifact_id: str
    parent_id: str | None
    payload: bytes

    @property
    def data(self):
        return decode_payload(self.payload)


def encode_artifact(artifact):
    return encode_payload({
        'kind': str(artifact.kind), 'id': artifact.artifact_id,
        'parent_id': artifact.parent_id, 'payload': encode_bytes(artifact.payload),
    })


def decode_artifact(data):
    fields = require_object(decode_payload(data), 'kind', 'id', 'parent_id', 'payload')
    kind, artifact_id, parent_id = fields['kind'], fields['id'], fields['parent_id']
    if kind not in ('calibration', 'report') or type(artifact_id) is not str or not artifact_id:
        raise ValueError('invalid artifact identity')
    if kind == 'calibration' and parent_id is not None:
        raise ValueError('calibration has an unexpected parent')
    if kind == 'report' and (type(parent_id) is not str or not parent_id):
        raise ValueError('report requires a calibration parent')
    return ArtifactEnvelope(kind, artifact_id, parent_id, decode_bytes(fields['payload']))
