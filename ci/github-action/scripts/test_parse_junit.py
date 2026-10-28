"""Tests for parse-junit.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parent / "parse-junit.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("parse_junit", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_testsuites_root(tmp_path: Path) -> None:
    xml = tmp_path / "junit.xml"
    xml.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<testsuites>\n'
        '  <testsuite tests="10" failures="2" errors="0" skipped="1"/>\n'
        '  <testsuite tests="5"  failures="0" errors="1" skipped="0"/>\n'
        '</testsuites>\n'
    )
    mod = _load_module()
    assert mod.parse(xml) == (15, 2, 1, 1)


def test_single_testsuite_root(tmp_path: Path) -> None:
    xml = tmp_path / "junit.xml"
    xml.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<testsuite tests="7" failures="3" errors="0" skipped="2"/>\n'
    )
    mod = _load_module()
    assert mod.parse(xml) == (7, 3, 0, 2)


def test_missing_attributes_default_to_zero(tmp_path: Path) -> None:
    xml = tmp_path / "junit.xml"
    xml.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<testsuites>\n'
        '  <testsuite tests="3"/>\n'
        '</testsuites>\n'
    )
    mod = _load_module()
    assert mod.parse(xml) == (3, 0, 0, 0)


def test_missing_file_returns_nonzero_via_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mod = _load_module()
    rc = mod.main(["parse-junit.py", str(tmp_path / "nope.xml")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "parse-junit" in err


def test_wrong_args_returns_2(capsys: pytest.CaptureFixture[str]) -> None:
    mod = _load_module()
    assert mod.main(["parse-junit.py"]) == 2
    assert "usage" in capsys.readouterr().err
