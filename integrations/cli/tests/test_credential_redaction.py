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


# Constants, deliberately. The input key is fixed, so the expected
# output is a constant and writing it as one is the whole control: an
# expectation computed by the same algorithm as the code moves when the
# code moves, and a diff touching both sides passes in silence. A
# literal forces that edit into the open.
#
# For FAKE_KEY: sha256(whole)[:6] is the mask; sha256(first 8)[:6] is
# what a digest-of-a-fragment would print; the plain prefix is what a
# truncation would print. All three differ, so one literal rules out
# both wrong constructions.
EXPECTED_MASK = "<set sha256:90aa62>"
FRAGMENT_DIGEST = "716cab"
PLAIN_PREFIX = "el_liv"


def test_repr_pins_the_exact_mask():
    assert f"api_key={EXPECTED_MASK}" in repr(Config(api_key=FAKE_KEY))


def test_repr_shows_neither_a_fragment_digest_nor_a_prefix():
    """The two constructions the absence check alone would let through.

    A six-character prefix is shorter than the eight-character run the
    absence test searches for, and a digest of the key's first eight
    characters is a digest of a fragment. Both disclose part of the
    secret; both pass an absence-only check.
    """
    text = repr(Config(api_key=FAKE_KEY))
    assert FRAGMENT_DIGEST not in text
    assert PLAIN_PREFIX not in text


def test_repr_carries_no_run_of_the_key():
    _assert_no_key_run(repr(Config(api_key=FAKE_KEY, base_url="https://example.test")))


def test_repr_marks_an_absent_key_as_none():
    assert "api_key=None" in repr(Config(api_key=None))


def test_repr_distinguishes_two_different_keys():
    a = repr(Config(api_key=FAKE_KEY))
    b = repr(Config(api_key="el_live_" + "B" * 43))
    assert a != b, "two different keys render identically — an operator cannot tell which key is wrong"


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
