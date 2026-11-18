from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class ManifestEntry:
    name: str
    size: int
    sha256: str

    def __post_init__(self):
        if type(self.name) is not str or not self.name:
            raise ValueError('invalid manifest name')
        if type(self.size) is not int or self.size < 0:
            raise ValueError('invalid manifest size')
        if (type(self.sha256) is not str or len(self.sha256) != 64
                or any(character not in '0123456789abcdef' for character in self.sha256)):
            raise ValueError('invalid manifest digest')


def build_manifest(members):
    return tuple(ManifestEntry(name, len(data), sha256(data).hexdigest())
                 for name, data in sorted(members.items()))


def check_manifest(manifest, members):
    declared = {entry.name: entry for entry in manifest}
    if len(declared) != len(manifest) or declared.keys() != members.keys():
        raise ValueError('manifest member set differs from package')
    for name, data in members.items():
        entry = declared[name]
        if len(data) != entry.size:
            raise ValueError(f'member length mismatch: {name}')
        if sha256(data).hexdigest() != entry.sha256:
            raise ValueError(f'member digest mismatch: {name}')
