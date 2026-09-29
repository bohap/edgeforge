"""Resolve provider identifiers to internal entity ids."""

import uuid
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from edgeforge.catalog.models import MappingMethod, ProviderEntityMap


def find_internal_id(
    session: Session, provider_id: uuid.UUID, entity_type: str, external_id: str
) -> uuid.UUID | None:
    return session.scalar(
        select(ProviderEntityMap.internal_id).where(
            ProviderEntityMap.provider_id == provider_id,
            ProviderEntityMap.entity_type == entity_type,
            ProviderEntityMap.external_id == external_id,
        )
    )


def resolve_or_create(
    session: Session,
    provider_id: uuid.UUID,
    entity_type: str,
    external_id: str,
    create: Callable[[], uuid.UUID],
) -> tuple[uuid.UUID, bool]:
    """Return the mapped internal id, creating the entity and mapping if unknown.

    Returns ``(internal_id, created)``.
    """
    existing = find_internal_id(session, provider_id, entity_type, external_id)
    if existing is not None:
        return existing, False
    internal_id = create()
    session.add(
        ProviderEntityMap(
            provider_id=provider_id,
            entity_type=entity_type,
            external_id=external_id,
            internal_id=internal_id,
            method=MappingMethod.AUTO,
            confidence=1.0,
        )
    )
    session.flush()
    return internal_id, True
