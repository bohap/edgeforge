"""Is the database migrated to the code's Alembic head?"""

from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"


@dataclass(frozen=True, slots=True)
class SchemaState:
    current: str | None
    head: str

    @property
    def up_to_date(self) -> bool:
        return self.current == self.head


def schema_state(engine: Engine, alembic_ini: Path = ALEMBIC_INI) -> SchemaState:
    config = Config(str(alembic_ini))
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise RuntimeError(f"no Alembic head found from {alembic_ini}")
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    return SchemaState(current=current, head=head)
