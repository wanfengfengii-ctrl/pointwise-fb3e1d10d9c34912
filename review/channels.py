from dataclasses import dataclass

from evidence.coordinates import compile_coefficients, require_integer


@dataclass(frozen=True)
class ChannelClaim:
    coefficients: tuple[int, ...]
    claimed: int


def compile_expressions(frame, expressions):
    if type(expressions) not in (list, tuple) or len(expressions) != 2:
        raise ValueError('review requires exactly two ordered expressions')
    return tuple(compile_coefficients(frame, expression) for expression in expressions)


def compile_channel_pair(frame, expressions, claims):
    if type(claims) not in (list, tuple) or len(claims) != 2:
        raise ValueError('report requires exactly two ordered integer claims')
    compiled = compile_expressions(frame, expressions)
    return tuple(
        ChannelClaim(coefficients, require_integer(claim, 'claim'))
        for coefficients, claim in zip(compiled, claims, strict=True)
    )
