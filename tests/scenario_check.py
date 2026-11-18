import unittest

from tests.test_calibration import CalibrationTests
from tests.test_handoff import HandoffTests
from tests.test_review import ReviewTests


class ShiftResult(unittest.TextTestResult):
    def addFailure(self, test, error):
        super().addFailure(test, error)
        # Errors such as fixture setup failures retain unittest's ordinary error output.
        traceback = error[2]
        while traceback is not None:
            if traceback.tb_frame.f_code.co_name == test._testMethodName:
                self.stream.writeln('SHIFT_RESULT_MISMATCH')
                break
            traceback = traceback.tb_next


def main():
    suite = unittest.TestSuite([
        CalibrationTests('test_integer_inconsistent'),
        CalibrationTests('test_modular_contradiction'),
        CalibrationTests('test_exact_marks'),
        ReviewTests('test_shared_parity'),
        ReviewTests('test_frozen_relation'),
        ReviewTests('test_zero_and_repeated'),
        HandoffTests('test_revision_isolation'),
        HandoffTests('test_exact_revision_selection'),
        HandoffTests('test_no_recompute'),
        ReviewTests('test_publish_retry'),
        ReviewTests('test_catalog_atomicity'),
    ])
    result = unittest.TextTestRunner(verbosity=2, resultclass=ShiftResult).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
