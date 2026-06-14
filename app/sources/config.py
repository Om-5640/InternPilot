"""Curated lists of company slugs to ingest per ATS.

Slugs are verified against live boards; 404s are removed.
"""
from __future__ import annotations

GREENHOUSE_SLUGS: list[str] = [
    # Consumer / social
    "airbnb",
    "reddit",
    "dropbox",
    # Fintech / payments
    "stripe",
    "brex",
    "coinbase",
    # Dev tools / infrastructure
    "figma",
    "databricks",
    "elastic",
    "fastly",
    "pagerduty",
    # Enterprise SaaS
    "asana",
    "mixpanel",
    # Cloud / data
    "datadog",
    "cloudflare",
    "mongodb",
]

# Lever v0 public posting API (/v0/postings/{slug}) returns 404 for all tested
# companies as of June 2026 — the endpoint appears to be deprecated.
LEVER_SLUGS: list[str] = []

# Ashby boards for these slugs return 200 with 0 active postings — the boards
# are valid but the companies currently have no open roles.  They are kept here
# so data flows in automatically when positions re-open.
ASHBY_SLUGS: list[str] = [
    "openai",
    "cohere",
    "perplexity",
    "cursor",
    "anyscale",
    "replit",
    "modal",
    "linear",
]
