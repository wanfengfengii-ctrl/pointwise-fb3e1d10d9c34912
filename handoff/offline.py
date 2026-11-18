import json
from dataclasses import dataclass

from archive.database import write_transaction
from archive.payloads import ArtifactEnvelope, decode_payload
from evidence.coordinates import require_integer, require_positive_integer, require_text
from evidence.revisions import EvidenceRef
from handoff.integrity import verify_bundle
from handoff.serialization import decode_bundle
from review.storage import (
    get_request_row, get_submission_row, has_withdrawal_row, insert_submission_row,
    insert_withdrawal_row,
)


class InvalidBundle(ValueError):
    pass


SIDES = ('left', 'right')
_REQUEST_FIELDS = frozenset(('request_id', 'calibration_id', 'expressions'))


@dataclass(frozen=True)
class OfflineReview:
    report: ArtifactEnvelope
    calibration_id: str
    evidence_refs: tuple[EvidenceRef, ...]


def open_bundle(data):
    try:
        verified = verify_bundle(decode_bundle(data))
    except (ValueError, TypeError, RecursionError) as error:
        raise InvalidBundle(str(error)) from error
    return OfflineReview(verified.report, verified.calibration.artifact_id, verified.evidence_refs)


def _check_request(request):
    if type(request) is not dict or request.keys() != _REQUEST_FIELDS:
        raise ValueError('request must carry request_id, calibration_id and expressions')
    require_text(request['request_id'], 'request ID')
    require_text(request['calibration_id'], 'calibration ID')
    expressions = request['expressions']
    if type(expressions) not in (list, tuple) or len(expressions) != 2:
        raise ValueError('request requires two ordered expressions')
    for expression in expressions:
        _check_expression(expression)
    return request


def _check_expression(expression):
    if type(expression) is not dict:
        raise ValueError('expression must be a coordinate mapping')
    for name, coefficient in expression.items():
        require_text(name, 'coefficient coordinate')
        require_integer(coefficient, 'coefficient')


def _check_side(side):
    if side not in SIDES:
        raise ValueError('side must be left or right')
    return side


def _message(request, kind, side, version):
    _check_request(request)
    _check_side(side)
    require_positive_integer(version, 'version')
    return {'kind': kind, 'request': {
        'request_id': request['request_id'],
        'calibration_id': request['calibration_id'],
        'expressions': request['expressions'],
    }, 'side': side, 'version': version}


def make_submission(request, side, version, claim):
    message = _message(request, 'submit', side, version)
    require_integer(claim, 'claim')
    message['claim'] = claim
    return json.dumps(message, ensure_ascii=False).encode('utf-8')


def make_withdrawal(request, side, version):
    message = _message(request, 'withdraw', side, version)
    return json.dumps(message, ensure_ascii=False).encode('utf-8')


def _decode_message(message):
    if type(message) is not bytes:
        raise ValueError('offline message must be UTF-8 bytes')
    try:
        decoded = decode_payload(message)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError(f'invalid offline message: {error}') from error
    if type(decoded) is not dict:
        raise ValueError('offline message must be an object')
    kind = decoded.get('kind')
    if kind == 'submit':
        fields = ('kind', 'request', 'side', 'version', 'claim')
    elif kind == 'withdraw':
        fields = ('kind', 'request', 'side', 'version')
    else:
        raise ValueError('message kind must be submit or withdraw')
    if decoded.keys() != set(fields):
        raise ValueError('unexpected message fields')
    return decoded


def _decode_request_field(data):
    if type(data) is not dict or data.keys() != _REQUEST_FIELDS:
        raise ValueError('message request must carry request_id, calibration_id and expressions')
    if type(data['request_id']) is not str or not data['request_id']:
        raise ValueError('request ID must be nonempty text')
    if type(data['calibration_id']) is not str or not data['calibration_id']:
        raise ValueError('calibration ID must be nonempty text')
    expressions = data['expressions']
    if type(expressions) is not list or len(expressions) != 2:
        raise ValueError('request requires two ordered expressions')
    for expression in expressions:
        _check_expression(expression)
    return data


def receive(connection, message):
    decoded = _decode_message(message)
    kind, side, version = decoded['kind'], decoded['side'], decoded['version']
    if side not in SIDES:
        raise ValueError('side must be left or right')
    require_positive_integer(version, 'version')
    request = _decode_request_field(decoded['request'])
    if kind == 'submit':
        require_integer(decoded['claim'], 'claim')
    with write_transaction(connection):
        row = get_request_row(connection, request['request_id'])
        if row is None:
            raise ValueError(f"unknown review request {request['request_id']!r}")
        calibration_id, saved_expressions = row
        if calibration_id != request['calibration_id']:
            raise ValueError('message calibration does not match the fixed request')
        saved = decode_payload(saved_expressions)
        if saved != request['expressions']:
            raise ValueError('message expressions do not match the fixed request')
        request_id = request['request_id']
        if kind == 'withdraw':
            insert_withdrawal_row(connection, request_id, side, version)
        else:
            claim = decoded['claim']
            existing = get_submission_row(connection, request_id, side, version)
            if existing is None:
                insert_submission_row(connection, request_id, side, version, claim)
            elif decode_payload(existing[0]) != claim:
                raise ValueError('submission conflicts with the first value for this key')
        eligible = (get_submission_row(connection, request_id, side, version) is not None
                    and not has_withdrawal_row(connection, request_id, side, version))
    return {'request_id': request_id, 'side': side, 'version': version, 'eligible': eligible}
