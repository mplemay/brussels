from __future__ import annotations

from typing import Final

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

Json: Final[JSON] = JSON().with_variant(JSONB(), "postgresql")
