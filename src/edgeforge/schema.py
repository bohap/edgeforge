"""Imports every module that defines tables, so ``metadata`` describes the full schema.

Alembic and the schema tests use this module; application code imports models directly.
"""

from edgeforge.catalog import models as catalog_models
from edgeforge.core.db import Base
from edgeforge.football import models as football_models
from edgeforge.ops import models as ops_models
from edgeforge.raw import models as raw_models

SCHEMAS: tuple[str, ...] = (
    catalog_models.SCHEMA,
    ops_models.SCHEMA,
    raw_models.SCHEMA,
    football_models.SCHEMA,
)
metadata = Base.metadata
