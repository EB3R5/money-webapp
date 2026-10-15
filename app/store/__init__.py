"""The SQLite store layer (ADR-0011): one module per entity, each owning its SQL.

`database` is the shared handle; `Store`/`Field` the base every entity module builds on.
Import an entity's store from its module (`from app.store.transactions import transactions`),
not from here, so a router's imports say which entities it touches."""

from .base import Field, Store  # noqa: F401
from .database import Database, database  # noqa: F401
