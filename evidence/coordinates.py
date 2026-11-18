from dataclasses import dataclass


def require_text(value, label):
    if type(value) is not str or not value:
        raise ValueError(f'{label} must be nonempty text')
    try:
        value.encode('utf-8')
    except UnicodeError as error:
        raise ValueError(f'{label} must be valid UTF-8 text') from error
    return value


def require_integer(value, label):
    if type(value) is not int:
        raise ValueError(f'{label} must be an integer')
    return value


def normalize_coordinates(names):
    if type(names) not in (tuple, list) or not 1 <= len(names) <= 8:
        raise ValueError('a batch needs one to eight ordered coordinates')
    result = tuple(require_text(name, 'coordinate') for name in names)
    if len(set(result)) != len(result):
        raise ValueError('coordinates must be unique')
    return result


@dataclass(frozen=True)
class CoordinateFrame:
    names: tuple[str, ...]

    def __post_init__(self):
        object.__setattr__(self, 'names', normalize_coordinates(self.names))


def compile_coefficients(frame, coefficients):
    if type(coefficients) is not dict:
        raise ValueError('coefficients must be a coordinate mapping')
    for name, coefficient in coefficients.items():
        require_text(name, 'coefficient coordinate')
        if name not in frame.names:
            raise ValueError(f'unknown coordinate {name!r}')
        require_integer(coefficient, 'coefficient')
    return tuple(coefficients.get(name, 0) for name in frame.names)


def named_coefficients(frame, row):
    return {name: value for name, value in zip(frame.names, row, strict=True) if value}
