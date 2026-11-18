from calibration.equations import apply_equation


def evaluate_joint_claim(relation, channels):
    remaining = relation
    for channel in channels:
        remaining = apply_equation(remaining, channel.coefficients, channel.claimed)
        if remaining is None:
            return False
    return True
