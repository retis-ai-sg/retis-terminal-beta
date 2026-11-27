"""RSS and Atom feeds as an Attas Data Source, with its own RSS Viewer (Local RSS: scripts/run_local_rss.py)."""
from .source import RSSDataSource, build_snapshot

__all__ = ['RSSDataSource', 'build_snapshot']
