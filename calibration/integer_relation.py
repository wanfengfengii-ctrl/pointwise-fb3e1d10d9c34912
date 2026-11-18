from dataclasses import dataclass


@dataclass(frozen=True)
class IntegerRelation:
    point: tuple[int, ...]
    directions: tuple[tuple[int, ...], ...]

    def __post_init__(self):
        width = len(self.point)
        if not 1 <= width <= 8 or len(self.directions) > width:
            raise ValueError('invalid integer relation dimensions')
        for vector in (self.point, *self.directions):
            if len(vector) != width or any(type(value) is not int for value in vector):
                raise ValueError('an integer relation requires exact integer vectors')


def full_integer_relation(width):
    if type(width) is not int or not 1 <= width <= 8:
        raise ValueError('invalid coordinate count')
    directions = tuple(tuple(int(column == axis) for column in range(width)) for axis in range(width))
    return IntegerRelation((0,) * width, directions)


def _dot(row, vector):
    return sum(a * b for a, b in zip(row, vector, strict=True))


def evaluate_linear_form(relation, row):
    return _dot(row, relation.point), tuple(_dot(row, direction) for direction in relation.directions)


def _bezout(left, right):
    a, b = abs(left), abs(right)
    s, next_s = 1, 0
    t, next_t = 0, 1
    while b:
        quotient, remainder = divmod(a, b)
        a, b = b, remainder
        s, next_s = next_s, s - quotient * next_s
        t, next_t = next_t, t - quotient * next_t
    return a, -s if left < 0 else s, -t if right < 0 else t


def _combine(left, right, s, t):
    return tuple(s * a + t * b for a, b in zip(left, right, strict=True))


def reduce_parameter_row(coefficients, directions):
    if not coefficients:
        return 0, directions
    leading = coefficients[0]
    columns = list(directions)
    for index, coefficient in enumerate(coefficients[1:], 1):
        if coefficient == 0:
            continue
        gcd, s, t = _bezout(leading, coefficient)
        left, right = columns[0], columns[index]
        # The two-column change has determinant 1, so parameters still range over all integers.
        columns[0] = _combine(left, right, s, t)
        columns[index] = _combine(left, right, -(coefficient // gcd), leading // gcd)
        leading = gcd
    if leading < 0:
        columns[0] = scale_vector(columns[0], -1)
        leading = -leading
    return leading, tuple(columns)


def scale_vector(vector, factor):
    return tuple(factor * value for value in vector)


def translate_point(point, direction, multiple):
    return _combine(point, direction, 1, multiple)
