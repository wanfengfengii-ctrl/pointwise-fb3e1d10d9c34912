from dataclasses import dataclass

from archive.catalog import ArtifactKind
from archive.lookup import read
from archive.payloads import require_list, require_object
from archive.publication import publish_artifact
from calibration.snapshot import decode_calibration
from evidence.coordinates import named_coefficients
from review.channels import compile_channel_pair
from review.joint import evaluate_joint_claim
from review.projection import decode_value_set, encode_value_set, project_channel


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


def assess(connection, calibration_id, expressions, claims, *, before_commit=None):
    artifact = read(connection, ArtifactKind.CALIBRATION, calibration_id)
    fixed = decode_calibration(artifact.data)
    frame = fixed.batch.frame
    channels = compile_channel_pair(frame, expressions, claims)
    reachable = tuple(project_channel(fixed.relation, channel.coefficients) for channel in channels)
    jointly_reachable = evaluate_joint_claim(fixed.relation, channels)
    payload = encode_assessment(frame, channels, reachable, jointly_reachable)
    report_id = publish_artifact(connection, ArtifactKind.REPORT, payload,
                                 parent_id=artifact.artifact_id, before_commit=before_commit)
    return Assessment(report_id, reachable, jointly_reachable)
