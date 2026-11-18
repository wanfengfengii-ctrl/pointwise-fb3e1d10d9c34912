from archive.catalog import ArtifactKind, get_catalog_entry
from archive.payloads import ArtifactEnvelope


class ArtifactNotFound(LookupError):
    pass


class ArtifactTypeMismatch(LookupError):
    pass


def read(connection, kind, artifact_id):
    kind = ArtifactKind(kind)
    if type(artifact_id) is not str or not artifact_id:
        raise ValueError('artifact ID must be nonempty text')
    row = get_catalog_entry(connection, artifact_id)
    if row is None:
        raise ArtifactNotFound(artifact_id)
    if kind != row[0]:
        raise ArtifactTypeMismatch(f'{artifact_id} has type {row[0]}, requested {kind}')
    return ArtifactEnvelope(*row)
