from archive.catalog import ArtifactKind
from archive.publication import publish_artifact
from calibration.congruences import apply_congruence
from calibration.equations import apply_equation
from calibration.integer_relation import full_integer_relation
from calibration.snapshot import FixedCalibration, encode_calibration
from evidence.revisions import EvidenceRef, fetch_revision, load_batch


class InvalidSelection(ValueError):
    pass


class InconsistentEvidence(ValueError):
    pass


def resolve_selection(connection, batch_id, evidence_refs):
    batch = load_batch(connection, batch_id)
    if type(evidence_refs) not in (list, tuple):
        raise InvalidSelection('provide an explicit ordered revision selection')
    refs = tuple(evidence_refs)
    if any(not isinstance(ref, EvidenceRef) or ref.batch_id != batch_id for ref in refs):
        raise InvalidSelection('every selected revision must belong to the requested batch')
    constraints = []
    for ref in refs:
        constraints.extend(fetch_revision(connection, ref).observations)
        if len(constraints) > 12:
            raise InvalidSelection('a selection may expand to at most twelve constraints')
    return batch, refs, tuple(constraints)


def admit_constraints(width, constraints):
    relation = full_integer_relation(width)
    for observation in constraints:
        if observation.modulus is None:
            relation = apply_equation(relation, observation.coefficients, observation.rhs)
        else:
            relation = apply_congruence(relation, observation.coefficients, observation.rhs,
                                        observation.modulus)
        if relation is None:
            raise InconsistentEvidence('selected evidence has no common integer solution')
    return relation


def calibrate(connection, batch_id, evidence_refs, *, before_commit=None):
    batch, refs, constraints = resolve_selection(connection, batch_id, evidence_refs)
    relation = admit_constraints(len(batch.coordinates), constraints)
    fixed = FixedCalibration(batch, refs, relation)
    return publish_artifact(connection, ArtifactKind.CALIBRATION, encode_calibration(fixed),
                            before_commit=before_commit)
