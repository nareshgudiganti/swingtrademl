"""The durable state of a module switch (#291): one row per optional module that has ever been switched.

No row means the module keeps its declared default (core/modules.py). A core module is never stored: the registry
refuses to switch one, and ignores a row that names one. Switching a module off changes this row and nothing else; the
module's own data is never touched.
"""

from __future__ import annotations

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base, TimestampMixin


class ModuleSwitch(Base, TimestampMixin):
    __tablename__ = "module_switches"

    module_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
