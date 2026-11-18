from dataclasses import dataclass

from archive.payloads import ArtifactEnvelope, decode_artifact, decode_payload
from calibration.snapshot import decode_calibration
from evidence.batches import check_batch_compatibility
from evidence.revisions import EvidenceRef, decode_revision
from handoff.manifest import check_manifest
from handoff.serialization import evidence_slots
from review.reports import validate_assessment_payload


@dataclass(frozen=True)
class VerifiedBundle:
    report: ArtifactEnvelope
    calibration: ArtifactEnvelope
    evidence_refs: tuple[EvidenceRef, ...]


def verify_bundle(document):
    members = document.members
    check_manifest(document.manifest, members)
    if not {'report', 'calibration'} <= members.keys():
        raise ValueError('bundle requires report and calibration members')
    report = decode_artifact(members['report'])
    calibration = decode_artifact(members['calibration'])
    if report.kind != 'report' or calibration.kind != 'calibration':
        raise ValueError('bundle artifact member types do not match their slots')
    if report.parent_id != calibration.artifact_id:
        raise ValueError('report parent does not match bundled calibration')
    fixed = decode_calibration(calibration.data)
    validate_assessment_payload(fixed.batch.frame, report.data)
    slots = evidence_slots(fixed.evidence_refs)
    if members.keys() != {'report', 'calibration', *slots}:
        raise ValueError('bundle evidence members do not match fixed selection')
    for name, expected_ref in slots.items():
        revision = decode_revision(decode_payload(members[name]))
        if revision.ref != expected_ref:
            raise ValueError(f'evidence reference mismatch: {name}')
        check_batch_compatibility(fixed.batch, revision.batch)
    return VerifiedBundle(report, calibration, fixed.evidence_refs)
