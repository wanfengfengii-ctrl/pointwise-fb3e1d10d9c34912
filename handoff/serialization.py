from dataclasses import dataclass

from archive.payloads import (
    decode_bytes, decode_payload, encode_bytes, encode_payload, require_list, require_object,
)
from handoff.manifest import ManifestEntry


@dataclass(frozen=True)
class BundleDocument:
    manifest: tuple[ManifestEntry, ...]
    members: dict[str, bytes]


def evidence_slots(refs):
    return {f'evidence/{number}': ref for number, ref in enumerate(dict.fromkeys(refs), 1)}


def encode_bundle(document):
    return encode_payload({
        'version': 1,
        'manifest': [{'name': item.name, 'size': item.size, 'sha256': item.sha256}
                     for item in document.manifest],
        'members': {name: encode_bytes(data) for name, data in document.members.items()},
    })


def decode_bundle(data):
    if type(data) is not bytes:
        raise ValueError('bundle must be bytes')
    fields = require_object(decode_payload(data), 'version', 'manifest', 'members')
    if type(fields['version']) is not int or fields['version'] != 1:
        raise ValueError('unsupported bundle version')
    if type(fields['members']) is not dict:
        raise ValueError('bundle members must be an object')
    manifest = tuple(ManifestEntry(**require_object(entry, 'name', 'size', 'sha256'))
                     for entry in require_list(fields['manifest']))
    if len({entry.name for entry in manifest}) != len(manifest):
        raise ValueError('duplicate manifest name')
    members = {name: decode_bytes(content) for name, content in fields['members'].items()}
    return BundleDocument(manifest, members)
