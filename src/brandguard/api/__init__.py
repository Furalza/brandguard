"""Product API: the web service an operator's browser talks to.

Everything here is a thin shell around the engine. The API owns three things
the engine deliberately does not: persistence (SQLite), background execution
(a small worker pool with per-source limits) and the operator vocabulary
(product.category). Run with ``python -m brandguard.api``.
"""
