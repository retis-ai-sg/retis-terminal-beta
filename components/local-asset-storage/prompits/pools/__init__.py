"""
Public package exports for `prompits.pools`.

Prompits provides the core HTTP-native agent runtime, Plaza coordination layer, and
pool/practice infrastructure for FinMAS. Within Prompits, the pools package implements
storage adapters and pool-specific helpers.

It re-exports `PostgresPool` lazily, so importing one pool module (for example
`prompits.pools.filesystem`) does not load the Postgres adapter and its driver.
"""

__all__ = ["PostgresPool"]


def __getattr__(name):
    """Load `PostgresPool` on first use."""
    if name == "PostgresPool":
        from .postgres import PostgresPool
        return PostgresPool
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
