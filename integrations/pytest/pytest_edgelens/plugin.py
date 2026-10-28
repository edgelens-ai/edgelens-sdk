"""pytest_edgelens plugin module.

Adds CLI options, fixtures, and JUnit metadata for tests that need a
real EdgeLens camera. Auto-loaded via the ``pytest11`` entry point.

Fixtures
--------
- ``edgelens_options`` — CLI/env-derived ``EdgelensOptions`` (session)
- ``edgelens_client`` — single ``EdgeLensClient`` for the run (session)
- ``edgelens_session`` — allocated ``Session``, scope per ``--edgelens-scope``
- ``device`` — the ``Device`` from the session (same scope)

Markers
-------
- ``@pytest.mark.edgelens(os="recamagined")`` — skip the test unless
  the active ``--edgelens-os`` matches the marker. Pairs with running
  pytest once per OS instead of mixing scopes.

CLI options
-----------
- ``--edgelens-key`` (env ``EDGELENS_API_KEY``)
- ``--edgelens-base-url``
- ``--edgelens-os`` (default ``stock-os``)
- ``--edgelens-device-type`` (default ``recamera-2002``)
- ``--edgelens-image-version`` (default ``None`` — platform picks)
- ``--edgelens-scope`` (``session``/``module``/``function``, default ``session``)
- ``--edgelens-session-timeout`` (seconds, default 3600)
- ``--edgelens-wait-timeout`` (seconds; **DEPRECATED** —
  wait_ready is now server-driven via the server's ``deadline`` field. The
  flag remains for one release as an explicit ceiling override, and
  emits a ``PytestDeprecationWarning`` when set.)
- ``--edgelens-skip-allocation`` — skip any test that requests
  ``edgelens_session``/``device`` (no platform call), for testing the
  plugin itself and collect-only runs.

JUnit metadata
--------------
On each test, the session id, device mac, host, os, and device-type are
recorded as ``<property>`` entries so JUnit consumers (GitLab MR
widget, GitHub Action summary, etc.) can show which device a test ran
on without parsing logs.
"""

from __future__ import annotations

import os
from typing import Optional

import pytest

from pytest_edgelens import lifecycle
from pytest_edgelens.lifecycle import EdgelensOptions


SCOPES = ("session", "module", "function")
DEFAULT_SCOPE = "session"


# ---- CLI options + marker registration --------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("edgelens", "EdgeLens device-farm options")
    group.addoption(
        "--edgelens-key", default=None,
        help="EdgeLens API key. Default: $EDGELENS_API_KEY.",
    )
    group.addoption(
        "--edgelens-base-url", default=None,
        help="Override the platform API base URL.",
    )
    group.addoption(
        "--edgelens-os", default="stock-os",
        help="OS to flash (default: stock-os; alt: recamagined).",
    )
    group.addoption(
        "--edgelens-device-type", default="recamera-2002",
        help="Device type to allocate (default: recamera-2002).",
    )
    group.addoption(
        "--edgelens-image-version", default=None,
        help=(
            "OS image version to flash. Omit to let the platform pick "
            "its default for --edgelens-os."
        ),
    )
    group.addoption(
        "--edgelens-scope", default=DEFAULT_SCOPE, choices=SCOPES,
        help=(
            "Fixture scope for `edgelens_session` and `device`. "
            "Default: session (cheapest — one camera for the whole run). "
            "Use module/function for fresh-per-module/test when tests mutate "
            "device state in ways the previous test would leave broken."
        ),
    )
    group.addoption(
        "--edgelens-session-timeout", default=3600, type=int,
        help="Max session duration in seconds (default: 3600).",
    )
    group.addoption(
        "--edgelens-wait-timeout", default=None, type=int,
        help=(
            "DEPRECATED: wait_ready is now server-driven via "
            "the server's `deadline` field — the platform commits to a "
            "readiness deadline and the SDK trusts it. This flag "
            "remains for one release as an explicit ceiling override "
            "(shortens the wait; never extends past the server "
            "deadline). Emits PytestDeprecationWarning when set."
        ),
    )
    group.addoption(
        "--edgelens-skip-allocation", action="store_true", default=False,
        help=(
            "Skip session allocation. Tests that request "
            "`edgelens_session`/`device` are skipped (not passed a None "
            "device). Useful for testing the plugin itself or collect-only "
            "runs."
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "edgelens(os=None, device_type=None): "
        "constrain a test to a specific (os, device_type). The test is "
        "skipped when --edgelens-os/--edgelens-device-type don't match.",
    )


# ---- Options + client + session fixtures -----------------------------------


@pytest.fixture(scope="session")
def edgelens_options(request: pytest.FixtureRequest) -> EdgelensOptions:
    cfg = request.config
    api_key = cfg.getoption("--edgelens-key") or os.environ.get("EDGELENS_API_KEY")
    wait_ready_timeout_s = cfg.getoption("--edgelens-wait-timeout")
    if wait_ready_timeout_s is not None:
        # warn when the deprecated flag is actually set. Absent
        # (default None) means the SDK trusts the server-signaled
        # deadline; no warning noise.
        import warnings
        warnings.warn(
            "--edgelens-wait-timeout is deprecated — wait_ready "
            "is now server-driven via the server's `deadline` field. Remove the "
            "flag unless you specifically need to shorten the wait for "
            "abort-early / testing.",
            pytest.PytestDeprecationWarning,
            stacklevel=2,
        )
    return EdgelensOptions(
        api_key=api_key,
        base_url=cfg.getoption("--edgelens-base-url"),
        device_type=cfg.getoption("--edgelens-device-type"),
        os=cfg.getoption("--edgelens-os"),
        image_version=cfg.getoption("--edgelens-image-version"),
        session_timeout_s=cfg.getoption("--edgelens-session-timeout"),
        wait_ready_timeout_s=wait_ready_timeout_s,
        skip_allocation=cfg.getoption("--edgelens-skip-allocation"),
    )


@pytest.fixture(scope="session")
def edgelens_client(edgelens_options: EdgelensOptions):  # type: ignore[no-untyped-def]
    if edgelens_options.skip_allocation:
        yield None
        return
    client = lifecycle.build_client(edgelens_options)
    try:
        yield client
    finally:
        client.close()


def _dynamic_scope(*, fixture_name: str, config: pytest.Config) -> str:
    del fixture_name  # unused
    return str(config.getoption("--edgelens-scope") or DEFAULT_SCOPE)


@pytest.fixture(scope=_dynamic_scope)  # type: ignore[arg-type]
def edgelens_session(
    edgelens_client, edgelens_options: EdgelensOptions
):  # type: ignore[no-untyped-def]
    if edgelens_options.skip_allocation or edgelens_client is None:
        # Skip — don't hand back a None session that the test would
        # then dereference into an AttributeError.
        pytest.skip("edgelens allocation disabled (--edgelens-skip-allocation)")
    session = lifecycle.allocate_session(edgelens_client, edgelens_options)
    try:
        yield session
    finally:
        lifecycle.release_session(session)


@pytest.fixture(scope=_dynamic_scope)  # type: ignore[arg-type]
def device(edgelens_session):  # type: ignore[no-untyped-def]
    # edgelens_session skips under --edgelens-skip-allocation, so a test
    # reaching here always has a real session.
    return edgelens_session.device


# ---- Marker handling: skip mismatched (os, device_type) --------------------


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    active_os = config.getoption("--edgelens-os")
    active_device = config.getoption("--edgelens-device-type")
    for item in items:
        marker = item.get_closest_marker("edgelens")
        if marker is None:
            continue
        required_os = marker.kwargs.get("os")
        required_device = marker.kwargs.get("device_type")
        if required_os is not None and required_os != active_os:
            item.add_marker(
                pytest.mark.skip(
                    reason=(
                        f"requires --edgelens-os={required_os}, "
                        f"got {active_os}"
                    )
                )
            )
        if required_device is not None and required_device != active_device:
            item.add_marker(
                pytest.mark.skip(
                    reason=(
                        f"requires --edgelens-device-type={required_device}, "
                        f"got {active_device}"
                    )
                )
            )


# ---- JUnit metadata: stamp device + session info on each testcase -----------


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo  # type: ignore[type-arg]
):  # type: ignore[no-untyped-def]
    outcome = yield
    if call.when != "call":
        return
    # Look up the session fixture without forcing it (avoid triggering
    # allocation for tests that didn't ask for it).
    request: Optional[pytest.FixtureRequest] = getattr(item, "_request", None)
    if request is None:
        return
    cache = getattr(request, "_fixture_defs", None) or {}
    fixturedef = cache.get("edgelens_session")
    if fixturedef is None or fixturedef.cached_result is None:
        return
    session = fixturedef.cached_result[0]
    if session is None:
        return

    # Stash the live session on the terminal reporter so
    # pytest_terminal_summary can print it without forcing a new
    # allocation. Set here (only when a test actually used the session)
    # rather than via an autouse fixture that would allocate on every run.
    reporter = item.config.pluginmanager.getplugin("terminalreporter")
    if reporter is not None:
        reporter._edgelens_session = session  # type: ignore[attr-defined]

    report = outcome.get_result()
    user_props = list(getattr(report, "user_properties", []) or [])
    user_props.append(("edgelens_session_id", session.id))
    conn = getattr(session, "_connection", None)
    if conn is not None:
        user_props.extend(
            [
                ("edgelens_mac", conn.mac),
                ("edgelens_host", conn.host),
                ("edgelens_os", conn.os.value),
            ]
        )
    report.user_properties = user_props


# ---- Terminal summary line -------------------------------------------------


# The session shown here is stashed on the
# terminal reporter by pytest_runtest_makereport — only when a test
# actually used `edgelens_session`. No autouse fixture, so a
# --collect-only / plugin-only / no-device run never forces a PAID
# allocation just to print a summary.
def pytest_terminal_summary(terminalreporter, exitstatus, config):  # type: ignore[no-untyped-def]
    if config.getoption("--collect-only", default=False):
        return
    if config.getoption("--edgelens-skip-allocation", default=False):
        return
    # Only read the session captured during the run; never allocate here.
    session = getattr(terminalreporter, "_edgelens_session", None)
    if session is None:
        return
    terminalreporter.write_sep("-", "edgelens", bold=True)
    terminalreporter.write_line(
        f"session {session.id} ({config.getoption('--edgelens-device-type')} / "
        f"{config.getoption('--edgelens-os')})"
    )
