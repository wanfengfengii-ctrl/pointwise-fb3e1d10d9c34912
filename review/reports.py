from dataclasses import dataclass

from archive.catalog import ArtifactKind, allocate_artifact_id, insert_catalog_entry
from archive.database import write_transaction
from archive.lookup import read
from archive.payloads import ArtifactEnvelope, encode_payload, require_list, require_object
from archive.publication import publish_artifact
from calibration.snapshot import decode_calibration
from evidence.coordinates import named_coefficients, require_positive_integer, require_text
from review.channels import compile_channel_pair, compile_expressions
from review.joint import evaluate_joint_claim
from review.projection import decode_value_set, encode_value_set, project_channel
from review.storage import (
    get_receipt_row, get_request_row, get_submission_row, has_withdrawal_row,
    insert_receipt_row, insert_request_row, request_expressions, submission_claim,
)


@dataclass(frozen=True)
class Assessment:
    report_id: str
    reachable: tuple
    jointly_reachable: bool


def encode_assessment(frame, channels, reachable, jointly_reachable):
    return {
        'channels': [
            {'coefficients': named_coefficients(frame, channel.coefficients),
             'claimed': channel.claimed, 'reachable': encode_value_set(values)}
            for channel, values in zip(channels, reachable, strict=True)
        ],
        'jointly_reachable': jointly_reachable,
    }


def validate_assessment_payload(frame, data):
    fields = require_object(data, 'channels', 'jointly_reachable')
    if type(fields['jointly_reachable']) is not bool:
        raise ValueError('invalid joint conclusion')
    channels = [require_object(item, 'coefficients', 'claimed', 'reachable')
                for item in require_list(fields['channels'])]
    compile_channel_pair(frame, [item['coefficients'] for item in channels],
                         [item['claimed'] for item in channels])
    for item in channels:
        decode_value_set(item['reachable'])


def build_assessment(connection, calibration_id, expressions, claims):
    artifact = read(connection, ArtifactKind.CALIBRATION, calibration_id)
    fixed = decode_calibration(artifact.data)
    frame = fixed.batch.frame
    channels = compile_channel_pair(frame, expressions, claims)
    reachable = tuple(project_channel(fixed.relation, channel.coefficients) for channel in channels)
    jointly_reachable = evaluate_joint_claim(fixed.relation, channels)
    payload = encode_assessment(frame, channels, reachable, jointly_reachable)
    return artifact, payload, Assessment('', reachable, jointly_reachable)


def assess(connection, calibration_id, expressions, claims, *, before_commit=None):
    artifact, payload, result = build_assessment(connection, calibration_id, expressions, claims)
    report_id = publish_artifact(connection, ArtifactKind.REPORT, payload,
                                 parent_id=artifact.artifact_id, before_commit=before_commit)
    return Assessment(report_id, result.reachable, result.jointly_reachable)


def create_review(connection, calibration_id, expressions):
    artifact = read(connection, ArtifactKind.CALIBRATION, calibration_id)
    fixed = decode_calibration(artifact.data)
    compiled = compile_expressions(fixed.batch.frame, expressions)
    ordered = [named_coefficients(fixed.batch.frame, coefficients) for coefficients in compiled]
    request_id = allocate_artifact_id()
    with write_transaction(connection):
        insert_request_row(connection, request_id, calibration_id, ordered)
    return {
        'request_id': request_id,
        'calibration_id': calibration_id,
        'expressions': ordered,
    }


def _load_request(connection, request_id):
    require_text(request_id, 'request ID')
    row = get_request_row(connection, request_id)
    if row is None:
        raise ValueError(f'unknown review request {request_id!r}')
    return row


def _eligible_original(connection, request_id, side, version):
    row = get_submission_row(connection, request_id, side, version)
    if row is None or has_withdrawal_row(connection, request_id, side, version):
        return None
    return submission_claim(row)


def finalize(connection, request_id, left_version, right_version, *, before_commit=None):
    require_positive_integer(left_version, 'left version')
    require_positive_integer(right_version, 'right version')
    with write_transaction(connection):
        request_row = _load_request(connection, request_id)
        existing = get_receipt_row(connection, request_id, left_version, right_version)
        if existing is not None:
            report_id = existing[0]
        else:
            claims = []
            for side, version in (('left', left_version), ('right', right_version)):
                claim = _eligible_original(connection, request_id, side, version)
                if claim is None:
                    raise ValueError(f'no eligible original submission for {side} version {version}')
                claims.append(claim)
            calibration_id = request_row[0]
            read(connection, ArtifactKind.CALIBRATION, calibration_id)
            _, payload, _ = build_assessment(connection, calibration_id,
                                             request_expressions(request_row), claims)
            report_id = allocate_artifact_id()
            insert_catalog_entry(connection, ArtifactEnvelope(
                ArtifactKind.REPORT, report_id, calibration_id, encode_payload(payload)))
            insert_receipt_row(connection, request_id, left_version, right_version, report_id)
            if before_commit is not None:
                before_commit(connection, report_id)
    return {
        'request_id': request_id,
        'left_version': left_version,
        'right_version': right_version,
        'report_id': report_id,
    }
