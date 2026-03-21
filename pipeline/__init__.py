"""
pipeline/ — Route registry, tracing, validation, and health for the Helios data pipeline.

Modules:
    route_index  — RouteContract dataclass + ROUTES registry (intent → sources → adapters → DB)
    tracing      — PipelineTrace and TraceSpan for structured span recording
    validation   — Per-intent scraper output contracts and validation
    health       — Startup self-check: verifies routes, adapters, and config
"""
