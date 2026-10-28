"""The API key must not survive into test output.

Two levels, and both are needed. The unit tests pin ``repr`` itself;
the pytester test goes through the path a key reaches output by —
pytest rendering fixture arguments when setup raises. A ``repr``
assertion alone can pass while the key still appears in real output,
because that exposure lies in how pytest renders the object, not in
anything the object's own tests call.
"""

from __future__ import annotations

import textwrap

import pytest

from pytest_edgelens.lifecycle import EdgelensOptions


# Obvious placeholder with the real shape: 8-char prefix + 43 chars.
FAKE_KEY = "el_live_" + "A" * 43


def _runs_of(value: str, n: int) -> set[str]:
    return {value[i:i + n] for i in range(len(value) - n + 1)}


def _assert_no_key_run(haystack: str, key: str = FAKE_KEY, n: int = 8) -> None:
    """Fail if any n-character run of ``key`` appears in ``haystack``.

    Whole-string absence is too weak: a mask that elides the middle
    still hands over a prefix, and a prefix of a secret is a piece of
    the secret.
    """
    leaked = sorted(run for run in _runs_of(key, n) if run in haystack)
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
    assert f"api_key={EXPECTED_MASK}" in repr(EdgelensOptions(api_key=FAKE_KEY))


def test_repr_shows_neither_a_fragment_digest_nor_a_prefix():
    """The two constructions the absence check alone would let through.

    A six-character prefix is shorter than the eight-character run the
    absence test searches for, and a digest of the key's first eight
    characters is a digest of a fragment. Both disclose part of the
    secret; both pass an absence-only check.
    """
    text = repr(EdgelensOptions(api_key=FAKE_KEY))
    assert FRAGMENT_DIGEST not in text
    assert PLAIN_PREFIX not in text


def test_repr_carries_no_run_of_the_key():
    opts = EdgelensOptions(api_key=FAKE_KEY)
    _assert_no_key_run(repr(opts))


def test_repr_marks_an_absent_key_as_none():
    assert "api_key=None" in repr(EdgelensOptions(api_key=None))


def test_repr_distinguishes_two_different_keys():
    a = repr(EdgelensOptions(api_key=FAKE_KEY))
    b = repr(EdgelensOptions(api_key="el_live_" + "B" * 43))
    assert a != b, "two different keys render identically — an operator cannot tell which key is wrong"


def test_repr_is_stable_for_the_same_key():
    assert repr(EdgelensOptions(api_key=FAKE_KEY)) == repr(EdgelensOptions(api_key=FAKE_KEY))


def test_repr_still_shows_the_other_fields():
    # The mask must not cost the diagnostic value of the rest of the repr.
    text = repr(EdgelensOptions(api_key=FAKE_KEY, device_type="recamera-2002"))
    assert "device_type='recamera-2002'" in text


FAILING_SETUP_CONFTEST = textwrap.dedent("""
    import pytest

    class _FakeClient:
        def close(self):
            pass

    @pytest.fixture(scope="session", autouse=True)
    def _fail_allocation():
        from pytest_edgelens import lifecycle as L

        def boom(client, opts):
            raise RuntimeError("allocation refused by the platform")

        mp = pytest.MonkeyPatch()
        mp.setattr(L, "build_client", lambda opts: _FakeClient())
        mp.setattr(L, "allocate_session", boom)
        yield
        mp.undo()
""")


@pytest.mark.parametrize("tb_style", ["long", "auto", "short", "line", "native"])
@pytest.mark.parametrize("showlocals", [True, False], ids=["showlocals", "default"])
def test_a_failing_session_setup_does_not_print_the_key(
    pytester: pytest.Pytester, tb_style: str, showlocals: bool
) -> None:
    """pytest renders fixture args on setup failure; the key must not show.

    Parametrised over traceback style and ``--showlocals`` because the
    rendering is pytest's, not ours. A mask verified under
    one combination says nothing about the others, and it is the
    customer who picks them — including in a CI config written long
    before they ever hit a failing allocation.
    """
    pytester.makeconftest(FAILING_SETUP_CONFTEST)
    pytester.makepyfile(
        textwrap.dedent("""
            def test_needs_a_device(device):
                assert device is not None
        """)
    )

    args = [f"--edgelens-key={FAKE_KEY}", f"--tb={tb_style}", "-v"]
    if showlocals:
        args.append("--showlocals")
    result = pytester.runpytest(*args)

    result.assert_outcomes(errors=1)
    _assert_no_key_run(str(result.stdout) + str(result.stderr))
