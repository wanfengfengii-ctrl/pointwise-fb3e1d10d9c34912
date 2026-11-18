from calibration.integer_relation import (
    IntegerRelation, evaluate_linear_form, reduce_parameter_row, translate_point,
)


def apply_equation(relation, row, rhs):
    base, coefficients = evaluate_linear_form(relation, row)
    divisor, directions = reduce_parameter_row(coefficients, relation.directions)
    delta = rhs - base
    if divisor == 0:
        return relation if delta == 0 else None
    parameter, remainder = divmod(delta, divisor)
    if remainder:
        return None
    point = translate_point(relation.point, directions[0], parameter)
    return IntegerRelation(point, directions[1:])
