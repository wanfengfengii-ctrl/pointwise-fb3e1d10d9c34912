from dataclasses import dataclass

from evidence.coordinates import compile_coefficients, require_integer


@dataclass(frozen=True)
class ChannelClaim:
    coefficients: tuple[int, ...]
    claimed: int


def compile_channel_pair(frame, expressions, claims):
    if type(expressions) not in (list, tuple) or len(expressions) != 2:
        raise ValueError('report requires exactly two ordered expressions')
    if type(claims) not in (list, tuple) or len(claims) != 2:
        raise ValueError('report requires exactly two ordered integer claims')
    return tuple(
        ChannelClaim(compile_coefficients(frame, expression), require_integer(claim, 'claim'))
        for expression, claim in zip(expressions, claims, strict=True)
    )
