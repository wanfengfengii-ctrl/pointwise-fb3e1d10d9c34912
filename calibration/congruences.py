from math import gcd

from calibration.integer_relation import (
    IntegerRelation, evaluate_linear_form, reduce_parameter_row, scale_vector, translate_point,
)


def apply_congruence(relation, row, rhs, modulus):
    if type(modulus) is not int or modulus <= 0:
        raise ValueError('modulus must be a positive integer')
    if modulus == 1:
        return relation
    base, coefficients = evaluate_linear_form(relation, row)
    divisor, directions = reduce_parameter_row(coefficients, relation.directions)
    delta = rhs - base
    if divisor == 0:
        return relation if delta % modulus == 0 else None
    common = gcd(divisor, modulus)
    if delta % common:
        return None
    period = modulus // common
    if period == 1:
        return relation
    inverse = pow(divisor // common, -1, period)
    parameter = ((delta // common) * inverse) % period
    point = translate_point(relation.point, directions[0], parameter)
    periodic_direction = scale_vector(directions[0], period)
    return IntegerRelation(point, (periodic_direction, *directions[1:]))
