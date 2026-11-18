import json
from contextlib import closing

from archive.catalog import initialize_store
from archive.database import open_database
from calibration.admission import calibrate
from evidence.batches import Batch
from evidence.revisions import record
from handoff.offline import make_submission, make_withdrawal, receive
from review.reports import assess


EXPRESSIONS = ({"x": 1}, {"y": 1})
ARRIVAL_ORDER = (
    ("submit", "left", 2, 1),
    ("submit", "left", 1, 0),
    ("submit", "right", 1, 1),
)
WITHDRAWAL_ORDER = (
    ("withdraw", "left", 2, None),
    ("submit", "left", 2, 1),
    ("submit", "left", 2, 1),
    ("submit", "left", 2, 0),
)
PAIR_CASES = (
    ((2, 1), (1, 1), True),
    ((1, 1), (0, 1), False),
)


def seed_calibration(db, modulus=2, revision="1"):
    batch = Batch("line-a", "tick", ("x", "y"))
    observations = [{"coefficients": {"x": 1, "y": 1}, "rhs": 0, "modulus": modulus}]
    ref = record(db, batch, "bench", revision, observations)
    return calibrate(db, batch.batch_id, [ref])


def replay(db, request, order):
    """Feed (kind, side, version, claim) rows in the listed arrival order.

    Withdrawal rows carry None in the claim slot. A conflicting final row raises
    ValueError, matching the wholesale rejection rule for illegal messages.
    """
    results = []
    for kind, side, version, claim in order:
        if kind == "submit":
            message = make_submission(request, side, version, claim)
        else:
            message = make_withdrawal(request, side, version)
        results.append(receive(db, message))
    return results


def main():
    results = []
    with closing(open_database(":memory:")) as db:
        initialize_store(db)
        calibration_id = seed_calibration(db)
        for versions, claims, expected in PAIR_CASES:
            result = assess(db, calibration_id, EXPRESSIONS, claims)
            if result.jointly_reachable is not expected:
                raise AssertionError(f"unexpected joint result for {claims!r}")
            results.append({"versions": versions, "claims": claims, "joint": result.jointly_reachable})
        corrected = seed_calibration(db, modulus=1, revision="2")
        after = assess(db, corrected, EXPRESSIONS, (0, 1)).jointly_reachable
        if after is not True:
            raise AssertionError("the modulus-1 calibration must admit (0, 1)")
    print(json.dumps({"reference_cases": results, "corrected_0_1_joint": after}, sort_keys=True))


if __name__ == "__main__":
    main()
