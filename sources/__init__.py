"""Event sources, in order of preference. Each module has NAME and fetch(today, horizon) -> list[dict].

To add a source: write a module with those two names and add it to SOURCES.
When two sources list the same event, the one earlier in this list wins and later ones only fill gaps.
"""
from . import nobel, scheltema, schouwburg, visitleiden

SOURCES = [visitleiden, schouwburg, scheltema, nobel]
