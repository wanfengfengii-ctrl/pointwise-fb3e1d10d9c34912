from archive.catalog import ArtifactKind, allocate_artifact_id, get_catalog_entry, insert_catalog_entry
from archive.database import write_transaction
from archive.payloads import ArtifactEnvelope, encode_payload


def publish_artifact(connection, kind, data, *, parent_id=None, before_commit=None):
    kind = ArtifactKind(kind)
    if kind == ArtifactKind.CALIBRATION and parent_id is not None:
        raise ValueError('a calibration cannot have an artifact parent')
    payload = encode_payload(data)
    artifact_id = allocate_artifact_id()
    artifact = ArtifactEnvelope(kind, artifact_id, parent_id, payload)
    with write_transaction(connection):
        if kind == ArtifactKind.REPORT:
            parent = get_catalog_entry(connection, parent_id)
            if parent is None or parent[0] != ArtifactKind.CALIBRATION:
                raise ValueError('report requires a committed calibration parent')
        insert_catalog_entry(connection, artifact)
        if before_commit is not None:
            before_commit(connection, artifact_id)
    return artifact_id
