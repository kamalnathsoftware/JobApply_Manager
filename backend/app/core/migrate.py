"""Apply pending Alembic migrations when the API starts, so pulling a new version never leaves
the database behind (which would show up as 500 errors on the new pages)."""

import logging
from pathlib import Path

from alembic.config import Config

from alembic import command

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]  # backend/


def upgrade_to_head() -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(cfg, "head")
