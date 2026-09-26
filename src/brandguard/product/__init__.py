"""Product layer: what an operator sees, built on top of the engine.

The engine speaks in six fine-grained labels (schema.Label) and separate
domain verdicts. An operator wants three answers: is this the brand's own
thing, is it a threat, or should someone look at it. This package holds the
translation and the input-resolution logic; nothing in here changes how the
engine decides.
"""
