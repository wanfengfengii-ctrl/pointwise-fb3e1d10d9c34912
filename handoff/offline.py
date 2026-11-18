from dataclasses import dataclass

from archive.payloads import ArtifactEnvelope
from evidence.revisions import EvidenceRef
from handoff.integrity import verify_bundle
from handoff.serialization import decode_bundle


class InvalidBundle(ValueError):
    pass


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
