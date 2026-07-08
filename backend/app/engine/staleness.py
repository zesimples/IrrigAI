"""Single source of truth for probe-reading staleness thresholds.

Daily-publishing providers (MyIrrigation / iMetos) deliver readings ~once a day,
so the original short cutoff (6h) flagged nearly every such sector as stale —
dropping confidence, demoting per-depth data_status, and firing connectivity
alerts on normal daily gaps.

Tiers (hours since the last reading):
- ``<= PROBE_STALE_H``            fresh (one normal daily-publish cycle)
- ``PROBE_STALE_H .. PROBE_VERY_STALE_H``  stale (a gap worth noting, still usable)
- ``> PROBE_VERY_STALE_H``        probe effectively dead — lean on the forecast and
                                  raise a connectivity alert

All probe-staleness consumers (confidence scoring, probe interpretation, ingestion
data_status, alert generation) import from here so the thresholds can't drift.
"""

PROBE_STALE_H = 30.0
PROBE_VERY_STALE_H = 72.0
