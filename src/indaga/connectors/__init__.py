"""Ingestion connectors (WS-1B.2).

Connectors know SOURCE FORMATS; adapters know STORAGE. A connector reads a source
(silver labs CSV, parsed Apple Health JSON, a DNA VCF) and writes `Fact`s /
`TimeSeries` into any `HealthlakeStore` through the port — so the same connector
populates the local DuckDB store today and a hosted vault later, unchanged.

Each connector is a plain function: ``ingest_*(store, subject_id, path, ...) -> int``.
"""
