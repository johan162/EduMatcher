from __future__ import annotations

import pytest

ABSENT = object()

BAD_VALUES = [
    pytest.param(None, id="none"),
    pytest.param(float("nan"), id="nan"),
    pytest.param(float("inf"), id="infinity"),
    pytest.param(-0.0, id="negative-zero"),
    pytest.param(ABSENT, id="absent-optional-key"),
    pytest.param("x" * 65_537, id="oversized-string"),
    pytest.param(1.5, id="non-integral-float"),
]
