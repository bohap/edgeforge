import pytest

from edgeforge.raw.blobstore import BlobNotFoundError, InMemoryBlobStore, blob_key_for


def test_key_is_content_addressed() -> None:
    assert blob_key_for(b"abc") == blob_key_for(b"abc")
    assert blob_key_for(b"abc") != blob_key_for(b"abd")
    assert blob_key_for(b"abc").startswith("sha256/")


def test_in_memory_round_trip_and_idempotent_put() -> None:
    store = InMemoryBlobStore()

    key = store.put(b'{"a": 1}')

    assert store.put(b'{"a": 1}') == key
    assert store.exists(key)
    assert store.get(key) == b'{"a": 1}'


def test_missing_blob_raises() -> None:
    with pytest.raises(BlobNotFoundError):
        InMemoryBlobStore().get("sha256/none")
