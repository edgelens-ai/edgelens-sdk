"""The API key must not survive into a traceback or terminal output.

``Config`` is the CLI's twin of the defect that fired in the pytest
plugin: a dataclass holding the key, whose generated repr printed it
anywhere the object reached a traceback.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgelens_cli import state as state_mod
from edgelens_cli.state import Config


# Obvious placeholder with the real shape: 8-char prefix + 43 chars.
FAKE_KEY = "el_live_" + "A" * 43


def _assert_no_key_run(haystack: str, key: str = FAKE_KEY, n: int = 8) -> None:
    """Fail if any n-character run of ``key`` appears in ``haystack``.

    Whole-string absence is too weak: a mask that elides the middle
    still hands over a prefix, and a prefix of a secret is a piece of
    the secret.
    """
    runs = {key[i:i + n] for i in range(len(key) - n + 1)}
    leaked = sorted(run for run in runs if run in haystack)
    assert not leaked, f"{len(leaked)} run(s) of the key survived: {leaked[:3]}"


# A literal, deliberately: an expectation computed by the same code as
# the mask moves when the code moves. FRAGMENT_DIGEST and
# WHOLE_KEY_DIGEST are six hex characters of sha256 over the key's first
# eight characters and over the whole key; PLAIN_PREFIX is what a
# truncation would print. None of them may appear.
EXPECTED_MASK = "<set>"
FRAGMENT_DIGEST = "716cab"
WHOLE_KEY_DIGEST = "90aa62"
PLAIN_PREFIX = "el_liv"


def test_repr_pins_the_exact_mask():
    assert f"api_key={EXPECTED_MASK}" in repr(Config(api_key=FAKE_KEY))


def test_repr_shows_no_digest_and_no_prefix():
    """The constructions the absence check alone would let through.

    A six-character prefix is shorter than the eight-character run the
    absence test searches for, and a short digest of the key or of a
    fragment of it confirms a guessed key offline. All of them pass an
    absence-only check.
    """
    text = repr(Config(api_key=FAKE_KEY))
    assert FRAGMENT_DIGEST not in text
    assert WHOLE_KEY_DIGEST not in text
    assert PLAIN_PREFIX not in text


def test_repr_carries_no_run_of_the_key():
    _assert_no_key_run(repr(Config(api_key=FAKE_KEY, base_url="https://example.test")))


def test_repr_marks_an_absent_key_as_none():
    assert "api_key=None" in repr(Config(api_key=None))


def test_repr_is_the_same_for_two_different_keys():
    """Nothing in the output depends on which key is set."""
    a = repr(Config(api_key=FAKE_KEY))
    b = repr(Config(api_key="el_live_" + "B" * 43))
    assert a == b


def test_repr_still_shows_the_base_url():
    assert "base_url='https://example.test'" in repr(
        Config(api_key=FAKE_KEY, base_url="https://example.test")
    )


def test_the_mask_does_not_change_what_is_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``repr=False`` must not reach ``asdict`` — login still saves the key.

    A mask that silently stopped the key being written would make
    every subsequent command re-prompt, and the test above would
    still pass.
    """
    monkeypatch.setattr(state_mod, "DEFAULT_DIR", tmp_path / "edgelens")
    monkeypatch.setattr(
        state_mod, "CONFIG_PATH", tmp_path / "edgelens" / "config.json"
    )

    state_mod.save_config(Config(api_key=FAKE_KEY, base_url="https://example.test"))

    written = json.loads((tmp_path / "edgelens" / "config.json").read_text())
    assert written["api_key"] == FAKE_KEY
    assert state_mod.load_config().api_key == FAKE_KEY
