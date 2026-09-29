"""Identifier generation. UUIDv7 keeps primary keys time-ordered and index-friendly."""

import uuid


def new_id() -> uuid.UUID:
    return uuid.uuid7()
