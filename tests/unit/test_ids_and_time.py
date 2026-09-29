from edgeforge.core.ids import new_id
from edgeforge.core.time import utcnow


def test_new_id_is_uuid7_and_time_ordered() -> None:
    ids = [new_id() for _ in range(100)]

    assert all(i.version == 7 for i in ids)
    assert ids == sorted(ids)


def test_utcnow_is_timezone_aware_utc() -> None:
    now = utcnow()

    assert now.utcoffset() is not None
    assert now.utcoffset().total_seconds() == 0
