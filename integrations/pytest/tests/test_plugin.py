"""End-to-end pytester tests for the plugin.

The plugin is auto-loaded via the `pytest11` entry point — pytester
inherits it. We stub the SDK's `EdgeLensClient` via a conftest that
the inner pytest pulls in.
"""

from __future__ import annotations

import textwrap

import pytest


STUB_CONFTEST = textwrap.dedent("""
    from unittest.mock import MagicMock
    import pytest

    @pytest.fixture(scope="session", autouse=True)
    def _stub_edgelens_client(monkeypatch_session):
        # Replace build_client so the plugin doesn't try to hit the network.
        from pytest_edgelens import lifecycle as L

        fake_client = MagicMock()
        fake_session = MagicMock()
        fake_session.id = "sess_stub"
        fake_session.status.value = "ready"
        fake_session._connection.mac = "aa:bb:cc:00:00:01"
        fake_session._connection.host = "192.0.2.42"
        fake_session._connection.os.value = "stock-os"
        fake_session.device = MagicMock(host="192.0.2.42", os="stock-os")
        fake_client.create_session.return_value = fake_session

        monkeypatch_session.setattr(L, "build_client", lambda opts: fake_client)
        monkeypatch_session.setattr(L, "allocate_session", lambda c, o: fake_session)
        monkeypatch_session.setattr(L, "release_session", lambda s: None)
        return fake_client


    @pytest.fixture(scope="session")
    def monkeypatch_session(request):
        # pytest 7+ provides this; older versions need a workaround.
        try:
            mp = pytest.MonkeyPatch()
        except AttributeError:
            from _pytest.monkeypatch import MonkeyPatch
            mp = MonkeyPatch()
        yield mp
        mp.undo()
""")


def test_device_fixture_runs(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(STUB_CONFTEST)
    pytester.makepyfile(
        textwrap.dedent("""
            def test_uses_device(device):
                assert device is not None
                assert device.host == "192.0.2.42"
        """)
    )
    result = pytester.runpytest("--edgelens-key", "el_test_k")
    result.assert_outcomes(passed=1)


def test_terminal_summary_prints_session(pytester: pytest.Pytester) -> None:
    """The end-of-run summary line prints the session id + target once a
    test has actually used the session. The hook must be defined once:
    a second definition would shadow it into a no-op."""
    pytester.makeconftest(STUB_CONFTEST)
    pytester.makepyfile(
        textwrap.dedent("""
            def test_uses_device(device):
                assert device is not None
        """)
    )
    result = pytester.runpytest("--edgelens-key", "el_test_k")
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["*edgelens*", "*session sess_stub*"])


def test_skip_allocation_skips_tests_needing_device(
    pytester: pytest.Pytester,
) -> None:
    """--edgelens-skip-allocation skips (not None-yields) a test that
    requests `device`, so it can't die with AttributeError on None."""
    pytester.makepyfile(
        textwrap.dedent("""
            def test_needs_device(device):
                raise AssertionError("should have been skipped, not executed")
        """)
    )
    result = pytester.runpytest("--edgelens-skip-allocation")
    result.assert_outcomes(skipped=1)


def test_skip_allocation_skips_tests_needing_session(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(
        textwrap.dedent("""
            def test_needs_session(edgelens_session):
                raise AssertionError("should have been skipped, not executed")
        """)
    )
    result = pytester.runpytest("--edgelens-skip-allocation")
    result.assert_outcomes(skipped=1)


def test_marker_skips_when_os_mismatch(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        textwrap.dedent("""
            import pytest

            @pytest.mark.edgelens(os="recamagined")
            def test_only_recamagined():
                pass

            @pytest.mark.edgelens(os="stock-os")
            def test_only_stock():
                pass

            def test_unmarked():
                pass
        """)
    )
    result = pytester.runpytest("--edgelens-skip-allocation", "--edgelens-os", "stock-os")
    result.assert_outcomes(passed=2, skipped=1)


def test_marker_skips_when_device_type_mismatch(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        textwrap.dedent("""
            import pytest

            @pytest.mark.edgelens(device_type="some-other-device")
            def test_other_device():
                pass

            def test_any_device():
                pass
        """)
    )
    result = pytester.runpytest("--edgelens-skip-allocation")
    result.assert_outcomes(passed=1, skipped=1)


def test_help_text_lists_options(pytester: pytest.Pytester) -> None:
    result = pytester.runpytest("--help")
    out = "\n".join(result.stdout.lines)
    assert "--edgelens-key" in out
    assert "--edgelens-os" in out
    assert "--edgelens-device-type" in out
    assert "--edgelens-scope" in out


def test_options_fixture_reflects_cli(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        textwrap.dedent("""
            def test_opts(edgelens_options):
                assert edgelens_options.os == "recamagined"
                assert edgelens_options.device_type == "recamera-2002"
                assert edgelens_options.session_timeout_s == 900
        """)
    )
    result = pytester.runpytest(
        "--edgelens-skip-allocation",
        "--edgelens-os", "recamagined",
        "--edgelens-session-timeout", "900",
    )
    result.assert_outcomes(passed=1)


def test_image_version_defaults_to_none(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        textwrap.dedent("""
            def test_opts(edgelens_options):
                assert edgelens_options.image_version is None
        """)
    )
    result = pytester.runpytest("--edgelens-skip-allocation")
    result.assert_outcomes(passed=1)


def test_image_version_flag_threads_to_options(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        textwrap.dedent("""
            def test_opts(edgelens_options):
                assert edgelens_options.image_version == "0.2.3"
        """)
    )
    result = pytester.runpytest(
        "--edgelens-skip-allocation",
        "--edgelens-image-version", "0.2.3",
    )
    result.assert_outcomes(passed=1)


def test_wait_timeout_flag_emits_deprecation_warning(
    pytester: pytest.Pytester,
) -> None:
    """--edgelens-wait-timeout is deprecated; setting it emits
    a PytestDeprecationWarning. Absence (default) is quiet."""
    pytester.makepyfile(
        textwrap.dedent("""
            def test_opts(edgelens_options):
                # Explicit setting threads through as caller-supplied ceiling
                assert edgelens_options.wait_ready_timeout_s == 120
        """)
    )
    result = pytester.runpytest(
        "--edgelens-skip-allocation",
        "--edgelens-wait-timeout", "120",
        "-W", "always",
    )
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["*is deprecated*"])


def test_wait_timeout_default_none_is_quiet(
    pytester: pytest.Pytester,
) -> None:
    """default (unset) is server-driven; no deprecation warning."""
    pytester.makepyfile(
        textwrap.dedent("""
            def test_opts(edgelens_options):
                assert edgelens_options.wait_ready_timeout_s is None
        """)
    )
    result = pytester.runpytest("--edgelens-skip-allocation", "-W", "error")
    result.assert_outcomes(passed=1)


def test_options_fixture_reads_env_key_when_no_flag(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDGELENS_API_KEY", "el_test_from_env")
    pytester.makepyfile(
        textwrap.dedent("""
            def test_env(edgelens_options):
                assert edgelens_options.api_key == "el_test_from_env"
        """)
    )
    result = pytester.runpytest("--edgelens-skip-allocation")
    result.assert_outcomes(passed=1)
