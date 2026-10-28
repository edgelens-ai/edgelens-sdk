"""Unit tests for the demo's output parsers and command builders.

Runs without a live device — the golden string below is the verbatim
stdout captured from a real face-detection run on a reCamaginedOS camera.
"""

from __future__ import annotations

import ast
import base64
import fnmatch
import hashlib
import inspect
import ipaddress
import pathlib
import shlex
import textwrap
import urllib.parse
import zlib
from datetime import datetime, timezone

import pytest

from qr_quiet_zone import measure

from demo_inference import (
    ARTIFACT_ACCOUNTING_NAME,
    Detection,
    ARTIFACT_QR_UNSPLIT_NAME,
    PASSWORD_REDACTED,
    ARTIFACT_RECORDS_NAME,
    ARTIFACT_RESULT_NAME,
    ARTIFACT_RUN_PREFIX,
    QR_UNSPLIT_EMPTY_NOTE,
    unsplit_artifact_text,
    BINARY_FILE,
    ANCHOR_FRAME_SIZE,
    BLANK_BITS_PER_PIXEL,
    CAPTURE_FILE,
    CAPTURE_PATH,
    FETCH_IMAGE_BOUND,
    KNEE_BYTES_RATIO,
    CAPTURE_RECORD_KEYWORDS,
    DECODER_FILE,
    STAGE_ONE_NOT_RUN,
    FEASIBILITY_QR,
    FEASIBILITY_QR_CANDIDATES,
    FEASIBILITY_QR_MODULES,
    FEASIBILITY_QR_URL,
    RETIRED_FLUSH_CROPPED_PAYLOADS,
    QR_PX_PER_MODULE_MEASURED_FAILING,
    QR_PX_PER_MODULE_MEASURED_PASSING,
    MODEL_FILE,
    QR_DECODED,
    QR_DIAGNOSTICS_MARKER,
    QR_PAYLOAD_ALPHABET,
    QR_PAYLOAD_BYTE_MAX,
    QR_PAYLOAD_BYTE_MIN,
    QR_PAYLOAD_LENGTH,
    QR_STDERR_PATH,
    QR_EXIT_STATUS,
    QR_EXIT_NO_OUTCOME,
    QR_FILE_ERROR,
    QR_NO_QR,
    QR_RECORD_PREFIX,
    QR_STATUSES,
    RESULT_PATH,
    accounting_table,
    annotated_frame_refusal,
    artifact_run_name,
    bits_per_pixel,
    bundled_inference_command,
    capture_command,
    capture_manifest_path,
    capture_output_paths,
    capture_series_glob,
    capture_stem,
    decode_chunk,
    fetch_chunk_command,
    fetched_artifact_name,
    fetched_length_disagreements,
    inference_command,
    jpeg_dimensions,
    listing_command,
    missing_record_keywords,
    models_dir,
    new_run_dir,
    parse_absent,
    parse_absent_globs,
    parse_capture_report,
    parse_digests,
    parse_inference,
    parse_qr_decode,
    parse_sizes,
    parse_stat,
    paths_not_cleared,
    payload_paths,
    NO_RED,
    DISPLAY_BYTES_UNVERIFIED,
    RED_FROM_DISPLAY_CHECK,
    RED_FROM_DISPLAYED_ARTIFACT,
    RED_FROM_PAYLOAD,
    RED_NOT_PERFORMED,
    attribute_red,
    display_bytes_unverified_note,
    verify_displayed_bytes,
    new_qr_payload,
    round_trip_refusal,
    stage_two_skip_reason,
    plan_capture_fetch,
    preflight_command,
    qr_decode_command,
    qr_payload_refusal,
    required_capture_span_px,
    size_disagreements,
    split_qr_output,
    stat_command,
    unmeasured_paths,
)

# Verbatim stdout from sscma-model on a live cam: sudo's "Password:" echo,
# ANSI-green "I" log lines, three candidate detections, one timing line.
GOLDEN = (
    "Password: \x1b[32mI engine load model /userdata/Models/scrfd_500m_kps_int8.cvimodel\x1b[0m\n"
    "\x1b[32mI model type: 15\x1b[0m\n"
    "x: 0.759033, y: 0.478516, w: 0.345215, h: -0.172852, score: 0.378459 target: 0\n"
    "x: 0.535156, y: 0.582031, w: 1.414062, h: 1.851562, score: 0.781331 target: 0\n"
    "x: 0.500000, y: 0.500000, w: 0.015747, h: 0.015747, score: 0.501968 target: 0\n"
    "\x1b[32mI pre: 2ms, infer: 11ms, post: 0ms\x1b[0m\n"
)


def test_parses_all_candidates_and_timing():
    r = parse_inference(GOLDEN)
    assert len(r.detections) == 3
    assert (r.pre_ms, r.infer_ms, r.post_ms) == (2, 11, 0)


def test_two_of_the_stored_boxes_are_not_shapes_and_are_rejected_as_such():
    """CORRECTED. This test used to assert that two of these count as faces.

    The stored output is the only sample of this model's behaviour that
    needs no device, and two of its three boxes are not rectangles: one
    has a negative height, and one is 1.4 by 1.9 times the frame it was
    found in. The previous version filtered them by score, found both
    above 0.5, and asserted that two faces were present — so our own
    suite certified impossible geometry as a detection.

    What is asserted here is the rejection and its reason, which pins the
    filter. The number of survivors is a consequence of that and is not
    the claim: asserting a count would be an assertion about what the
    model found, which this example deliberately never makes.
    """
    r = parse_inference(GOLDEN)
    rejected = {(round(d.w, 6), round(d.h, 6)): reason for d, reason in r.rejected}

    assert (0.345215, -0.172852) in rejected
    assert "height -0.172852 is not positive" in rejected[(0.345215, -0.172852)]

    assert (1.414062, 1.851562) in rejected
    assert "not contained in the frame" in rejected[(1.414062, 1.851562)]

    # Nothing is dropped: every emitted box is either a candidate or
    # carries a reason, and the raw list still holds all three.
    assert len(r.detections) == 3
    assert len(r.candidates) + len(r.rejected) == len(r.detections)


def test_faces_does_not_return_boxes_that_are_not_shapes():
    """The scoring helper filters geometry too, and nothing else checked it.

    This is the function a reader of this example calls. The run itself
    uses `candidates`, so without this the published helper was the
    untested path and the internal one was the tested path — the wrong
    way round.

    Identified by geometry rather than by counting what survives: a count
    would be an assertion about what the model found, which this example
    does not make.

    Only one of the two is evidence about geometry, which is why the
    scores are asserted as well. The negative-height box scores below
    the threshold, so a score-only helper would have dropped it anyway
    and its absence proves nothing. The box larger than the frame scores
    above the threshold, so geometry is the only thing that can exclude
    it.

    Every comparison goes through one threshold, including the ones on
    the stored scores, so that raising it fails loudly here instead of
    quietly decoupling this test from what it measures: above 0.781 the
    oversized box becomes score-excluded too, and absence would stop
    being evidence about geometry at all.

    And the valid box is asserted present, not merely the other two
    absent. Every absence here is vacuously true of an empty result —
    `all()` over nothing included — so without it a helper returning
    nothing at all would satisfy the whole test.
    """
    threshold = 0.5
    r = parse_inference(GOLDEN)
    kept = {(round(d.w, 6), round(d.h, 6)) for d in r.faces(min_score=threshold)}
    scores = {(round(d.w, 6), round(d.h, 6)): d.score for d in r.detections}

    # Presence first: the result is not empty, so the absences below mean
    # something.
    assert (0.015747, 0.015747) in kept

    assert (0.345215, -0.172852) not in kept
    assert (1.414062, 1.851562) not in kept

    assert scores[(0.345215, -0.172852)] < threshold   # excluded by score too
    assert scores[(1.414062, 1.851562)] >= threshold   # excluded ONLY by geometry
    assert all(d.is_valid for d in r.faces(min_score=threshold))


def test_the_highest_scoring_stored_box_is_one_of_the_rejected_ones():
    """CORRECTED. This test used to read as "a high-confidence face".

    The 0.781 box is the one measuring 1.4 by 1.9 times the frame. Its
    score was never evidence of a face; it was evidence that score and
    geometry are independent, which is why a filter on geometry is not a
    filter on confidence.
    """
    r = parse_inference(GOLDEN)
    top = max(r.detections, key=lambda d: d.score)
    assert top.score == pytest.approx(0.781331, abs=1e-5)
    assert not top.is_valid
    assert all(d.score <= 0.75 for d in r.candidates)


def test_missing_timing_line_raises():
    with pytest.raises(ValueError):
        parse_inference("Password: \nno inference happened\n")


# ---- a box that is not a shape is not a candidate ---------------------------
#
# Boxes are a centre and a size, normalised to the frame. A negative
# height is not a small box or an uncertain one; a box wider than the
# frame is not a box that happens to overflow. Counting either as a
# candidate reports a detection at the moment the model has said
# something went wrong.
#
# They are rejected and recorded, never dropped. The model's output is
# not fixed, these are its visible symptom, and a filter that hid them
# would be the last anyone saw of it.


def box(w=0.2, h=0.2, x=0.5, y=0.5, score=0.9):
    return Detection(x=x, y=y, w=w, h=h, score=score, target=0)


def test_a_box_inside_the_frame_is_a_candidate():
    assert box().is_valid
    assert box().invalid_reason is None


@pytest.mark.parametrize("w", [0.0, -0.001, -0.345])
def test_a_non_positive_width_is_not_a_shape(w):
    assert "width" in box(w=w).invalid_reason


@pytest.mark.parametrize("h", [0.0, -0.001, -0.172852])
def test_a_non_positive_height_is_not_a_shape(h):
    assert "height" in box(h=h).invalid_reason


@pytest.mark.parametrize(
    "x,y,w,h",
    [
        (0.1, 0.5, 0.4, 0.2),   # over the left edge
        (0.9, 0.5, 0.4, 0.2),   # over the right edge
        (0.5, 0.1, 0.2, 0.4),   # over the top
        (0.5, 0.9, 0.2, 0.4),   # over the bottom
        (0.5, 0.5, 1.4, 1.9),   # larger than the frame in both directions
    ],
)
def test_a_box_leaving_the_frame_is_not_a_candidate(x, y, w, h):
    assert "not contained in the frame" in box(x=x, y=y, w=w, h=h).invalid_reason


def test_a_box_exactly_filling_the_frame_is_still_a_candidate():
    # The bound is inclusive on purpose: a box flush with the edges is a
    # shape, and rejecting it would discard a legitimate full-frame
    # detection for being exactly as large as it is allowed to be.
    assert box(x=0.5, y=0.5, w=1.0, h=1.0).is_valid


def test_the_width_reason_is_given_before_the_containment_one():
    # A box with no width has no meaningful edges, so reporting where its
    # edges fall would describe a shape that does not exist.
    reason = box(w=-0.5, x=0.0).invalid_reason
    assert "width" in reason
    assert "contained" not in reason


def test_the_bundled_capture_binary_reports_what_it_wrote():
    """The binary that ships must be one that reports its frames.

    An older build captured a single frame and reported nothing, so the
    record parser finds no schedule and raises — and it raises on the
    device, minutes into a run, with a session allocated and a camera
    already reflashed. This is the same failure for the price of a
    second, before anything is booked.

    Keywords rather than a digest, deliberately: a digest pin has to be
    edited by hand after every legitimate rebuild, and a check that must
    be edited to keep passing is one the next reader removes. The
    keywords are the behaviour actually being relied on.
    """
    data = (models_dir() / CAPTURE_FILE).read_bytes()
    assert missing_record_keywords(data) == ()


def test_the_pin_rejects_a_binary_that_reports_nothing():
    """The negative control, and it is a real file rather than a mock.

    `sscma-model` is the other tracked binary in this payload. It is a
    genuine executable for the same device and it carries none of the
    record keywords, so it stands in for exactly the mistake this pin
    exists to catch: shipping a binary that cannot report.

    Chosen over the previous build fetched out of git history on purpose
    — history is not a fixture. A control pinned to a historical commit
    stops working the day history is rewritten, and it would then be
    deleted rather than repaired.
    """
    wrong = (models_dir() / BINARY_FILE).read_bytes()
    assert len(wrong) > 0
    assert set(missing_record_keywords(wrong)) == set(CAPTURE_RECORD_KEYWORDS)


def test_every_pinned_keyword_is_checked_individually():
    """A keyword dropped one at a time must still be caught.

    Asserting only on the full set would pass a binary that kept one
    keyword and lost the rest, and a partial build is the likelier
    accident than a wholly wrong file.
    """
    data = (models_dir() / CAPTURE_FILE).read_bytes()
    for keyword in CAPTURE_RECORD_KEYWORDS:
        without = data.replace(keyword.encode(), b"\x00" * len(keyword))
        assert missing_record_keywords(without) == (keyword,)


def test_payload_files_exist():
    payload = payload_paths()
    for p in payload.all_paths():
        assert p.is_file(), f"missing bundled demo payload: {p}"
    assert payload.model.stat().st_size > 100_000
    assert payload.capture_binary.stat().st_size > 10_000


def test_deployed_files_exclude_the_model():
    payload = payload_paths()
    files = payload.as_files()
    assert str(payload.model) not in files
    assert str(payload.capture_binary) in files


def test_the_decoder_is_deployed_with_the_rest_of_the_payload():
    """The failure this is written against, stated as a scenario.

    The decoder is tracked beside the other binaries, which is easy to
    mistake for it being on the device. Nothing deploys a file because it
    is tracked: it reaches the camera only by being in the list handed to
    deploy. Left out, every check up to the decode passes — the session
    is created, the display reports the image, the camera captures a
    frame — and the run then fails at the exec on a file that was never
    sent, minutes into a window that costs a flash cycle to open.
    """
    payload = payload_paths()
    assert str(payload.decoder_binary) in payload.as_files()
    assert payload.decoder_binary.name == DECODER_FILE


def test_everything_in_the_payload_is_delivered_by_one_route_or_the_other():
    """The general form of the defect above, and it will recur.

    What the example tracks and what it sends were two different sets
    with nothing comparing them, which is how a binary sat beside the
    others for a week without ever reaching a device. The check that
    would have caught it is not about any one file: every member of the
    payload must leave by one of the two routes, the model separately and
    everything else in the deploy list. A field added here and forgotten
    there fails this, whatever it is called — which matters because the
    next two additions are already known.
    """
    payload = payload_paths()
    files = set(payload.as_files())
    for path in payload.all_paths():
        assert str(path) == str(payload.model) or str(path) in files, (
            f"{path} is part of the payload and is sent by neither route, so "
            f"it would be missing on the device with nothing reporting it"
        )


# --- command builders ------------------------------------------------------


def test_commands_pass_the_password_on_stdin_not_as_an_argument():
    for cmd in (
        preflight_command("s3cr3t pw"),
        capture_command("s3cr3t pw"),
        inference_command("s3cr3t pw"),
        stat_command("s3cr3t pw", "/userdata/Models/capture.jpg"),
        qr_decode_command("s3cr3t pw"),
        fetch_chunk_command("s3cr3t pw", "/x", 0, 10),
    ):
        assert "sudo -S" in cmd
        # single-quoted so a password with spaces stays one shell token
        assert "'s3cr3t pw'" in cmd


def test_capture_command_marks_the_binary_runnable_and_sets_the_library_path():
    cmd = capture_command("pw")
    assert f"chmod +x /userdata/Models/{CAPTURE_FILE}" in cmd
    # capture_jpeg's documented runtime path, not the inference binary's
    assert "/usr/lib64:/mnt/system/lib" in cmd
    assert CAPTURE_PATH in cmd


def test_inference_command_runs_on_the_captured_frame_by_default():
    cmd = inference_command("pw")
    assert f"chmod +x /userdata/Models/{BINARY_FILE}" in cmd
    assert "LD_LIBRARY_PATH=/mnt/system/lib" in cmd
    assert f"/userdata/Models/{MODEL_FILE}" in cmd
    assert CAPTURE_PATH in cmd
    assert RESULT_PATH in cmd


def test_bundled_command_is_the_sample_image_and_is_not_the_demo_path():
    bundled = bundled_inference_command("pw")
    assert "sample_faces.jpg" in bundled
    assert CAPTURE_PATH not in bundled
    # the demo default must not silently be the bundled image
    assert "sample_faces.jpg" not in inference_command("pw")


def test_the_gate_starts_shut_and_only_a_pass_opens_it():
    """Closed by default, because the likeliest failures never assert.

    A loader that cannot find a library, a rate limit, a capture that
    never arrives — each ends the first stage before it judges anything.
    A gate keyed on whether the stage ran would let all of them through,
    and they are precisely the failures a live run produces.
    """
    assert stage_two_skip_reason(STAGE_ONE_NOT_RUN) is not None
    assert stage_two_skip_reason(None) is None


def test_the_skip_reason_names_the_failure_rather_than_announcing_one():
    """A bare skip is an absent result wearing a label.

    It cannot be told from a stage nobody wrote, so the reason has to
    travel with the refusal and has to carry the first stage's own words.
    """
    reason = stage_two_skip_reason("display-check — the run stopped at the display check")
    assert reason is not None
    assert "the run stopped at the display check" in reason
    assert "attributed to the detector" in reason


def test_every_red_the_first_stage_can_produce_shuts_the_gate():
    """The gate is not keyed on one failure mode.

    Each attribution the first stage can reach other than a clean pass
    must close it, including the one that reports the stage was never
    performed — that is the case a human reading a report is most likely
    to wave through.
    """
    for source in (RED_FROM_PAYLOAD, RED_FROM_DISPLAY_CHECK, RED_NOT_PERFORMED):
        assert stage_two_skip_reason(f"{source} — because") is not None


def test_the_displayed_code_is_the_one_committed_here():
    """The failure this is written against, and it has already happened.

    The code that was chosen lived in this repository only as a fixture,
    measured and digest-pinned, while the display path still carried the
    two it replaced. Everything said about the margin was true of the
    fixture and false of what a run would have photographed, and nothing
    connected the two well enough to notice. A window spent that way
    returns a red that means nothing.

    So the address, the committed copy and the digest are one record.
    The digest is the identity because the address is not one: the file
    behind it can be replaced in place without the address changing, and
    a margin measured from one file while another is displayed measures
    nothing. That reasoning is why this record exists and it is not
    weakened below.

    What this test checks, exactly two things, both offline: the
    committed copy hashes to the recorded digest, and every candidate
    the run displays is the recorded *address*. It compares url strings,
    not bytes — the second half is a string comparison and establishes
    nothing about what that address serves.

    The remote bytes are verified in the demo path, not here. The device
    fetches the address itself, so those bytes never reach this harness,
    and this suite runs with the network denied. The demo fetches the
    address once before it spends the window and hands what arrives to
    ``verify_displayed_bytes``; the tests below pin that comparison on
    bytes fed in directly.
    """
    fixture = pathlib.Path(__file__).resolve().parent.parent / FEASIBILITY_QR.fixture
    assert fixture.is_file(), f"the committed copy is missing: {fixture}"
    assert (
        hashlib.sha256(fixture.read_bytes()).hexdigest() == FEASIBILITY_QR.sha256
    ), "the committed copy is not the bytes the measurement is attached to"

    for url in FEASIBILITY_QR_CANDIDATES:
        assert url == FEASIBILITY_QR.url, (
            "the run displays something other than the measured artifact"
        )


def test_the_measured_artifact_is_accepted_and_anything_else_is_refused():
    """The comparison the whole record was for, and it had no teeth.

    Everything above pins the committed copy and the url string. Neither
    touches the bytes the device actually fetches, so a re-render at that
    address would have invalidated every margin figure with the suite
    still green — which is precisely the failure the record was written
    to prevent, one layer further out.

    Both directions are pinned here. A digest check that cannot fail is
    the defect being fixed, so the refusal is the half that matters.
    """
    fixture = pathlib.Path(__file__).resolve().parent.parent / FEASIBILITY_QR.fixture
    measured = fixture.read_bytes()

    accepted = verify_displayed_bytes(measured, FEASIBILITY_QR)
    assert accepted.matches
    assert accepted.mismatch_reason is None
    assert accepted.actual_sha256 == FEASIBILITY_QR.sha256
    assert accepted.size_bytes == len(measured)

    # A re-render is a different image at the same address, and one byte
    # is enough to be one.
    refused = verify_displayed_bytes(measured + b"\x00", FEASIBILITY_QR)
    assert not refused.matches
    assert refused.mismatch_reason is not None


def test_the_refusal_names_both_digests_and_the_address_they_came_from():
    """A bool here would send the reader back to the file.

    The one thing somebody needs from this failure is which image they
    have, and that is both digests next to the address that served the
    wrong one. It is also the reason the result is a record rather than
    a bool: there is nowhere else for those three strings to travel.
    """
    other = verify_displayed_bytes(b"not a QR code at all", FEASIBILITY_QR)
    reason = other.mismatch_reason
    assert reason is not None
    # Printed because what this failure says is the thing worth checking
    # by eye, and a passing test shows nothing by default.
    print(f"\n{RED_FROM_DISPLAYED_ARTIFACT} — {reason}")
    assert FEASIBILITY_QR.url in reason
    assert FEASIBILITY_QR.sha256 in reason
    assert other.actual_sha256 in reason
    assert other.actual_sha256 != FEASIBILITY_QR.sha256


def test_a_fetch_that_failed_is_reported_rather_than_read_as_a_mismatch():
    """Getting this wrong the other way is worse than the bug.

    The harness's network is not the one the device fetches over, so a
    blip here is evidence about neither the artifact nor the display.
    Ending the run on it would turn a recoverable error into a lost
    window, and the window is the expensive thing.

    What it must not do is pass quietly: a check that says nothing when
    it did not run reads afterwards exactly like one that passed, so the
    note says the margin is unverified for that run and names the digest
    nothing was compared against.
    """
    note = display_bytes_unverified_note(FEASIBILITY_QR, "URLError: timed out")
    print(f"\n{note}")
    assert note.startswith(DISPLAY_BYTES_UNVERIFIED)
    assert FEASIBILITY_QR.url in note
    assert FEASIBILITY_QR.sha256 in note
    assert "timed out" in note
    assert "unverified" in note
    assert "not a mismatch" in note


def test_the_verification_fetches_nothing_itself():
    """Why it is a function over bytes and not over a url.

    This suite runs with the network denied, and that is the property
    being protected rather than an inconvenience: a check that fetched
    would be untestable exactly where it has to be pinned, and a fetch
    that crept into import or collection time would break the whole
    offline target. So the I/O stays in the demo path and the decision
    stays here, over bytes handed straight in.
    """
    source = inspect.getsource(verify_displayed_bytes)
    assert "urlopen" not in source
    assert "urllib" not in source
    assert "requests" not in source
    assert "open(" not in source


def test_the_served_bytes_are_checked_before_the_window_is_spent():
    """Order, which is the only thing that makes the check worth having.

    Asked after the deploy and the display requests, it can no longer
    save the window — it can only decline to report a run that already
    happened, which is what the margin figures being invalid already did.
    Asserted against the parsed source because the ordering does not
    need a rented device, and because a check that the call appears
    somewhere in the body would pass on the arrangement this refuses.
    """
    import test_demo_end_to_end as e2e

    body = ast.parse(
        inspect.getsource(e2e.test_the_displayed_code_is_read_back_out_of_the_photograph)
    ).body[0].body
    statements = [
        node
        for node in body
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))
    ]
    first = statements[0]
    assert (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Call)
        and isinstance(first.value.func, ast.Name)
        and first.value.func.id == "_refuse_an_unmeasured_code"
    ), (
        "the first thing the run does must be to check that the address "
        f"still serves the measured artifact, and it is {ast.dump(first)}"
    )


def test_the_run_stops_when_the_address_serves_different_bytes(monkeypatch):
    """The refusal has to happen in the run, not only be decidable.

    Everything else here pins the comparison. This pins the only thing
    that spends or saves a window: that the run consults it and stops.
    The fetch is replaced rather than performed, because the suite has
    no network and the stopping does not need one.
    """
    import test_demo_end_to_end as e2e

    monkeypatch.setattr(e2e, "_fetch_served_bytes", lambda url: b"a re-rendered image")
    with pytest.raises(pytest.fail.Exception) as refused:
        e2e._refuse_an_unmeasured_code()

    message = str(refused.value)
    assert message.startswith(RED_FROM_DISPLAYED_ARTIFACT)
    assert FEASIBILITY_QR.url in message
    assert FEASIBILITY_QR.sha256 in message
    assert hashlib.sha256(b"a re-rendered image").hexdigest() in message


def test_the_run_continues_when_the_fetch_itself_fails(monkeypatch):
    """A blip must not cost the window, and must not pass quietly either.

    The note carries the unverified margin to the run's output; what is
    asserted here is only that nothing was raised, because raising is
    the expensive mistake.
    """
    import test_demo_end_to_end as e2e

    def refuse_to_connect(url: str) -> bytes:
        raise OSError("network is unreachable")

    monkeypatch.setattr(e2e, "_fetch_served_bytes", refuse_to_connect)
    assert e2e._refuse_an_unmeasured_code() is None


def test_the_check_is_transparent_when_the_address_still_serves_the_artifact(monkeypatch):
    """A check that refuses a correct address is one nobody keeps."""
    import test_demo_end_to_end as e2e

    fixture = pathlib.Path(__file__).resolve().parent.parent / FEASIBILITY_QR.fixture
    measured = fixture.read_bytes()
    monkeypatch.setattr(e2e, "_fetch_served_bytes", lambda url: measured)
    assert e2e._refuse_an_unmeasured_code() is None


def test_the_refusal_is_attributed_like_every_other_red():
    """A fourth attribution, kept apart from the three outcomes.

    It is not something a run produced — it is a refusal to spend one —
    and collapsing it into the display check would report a run that
    never started as a display that never settled.
    """
    for source in (RED_FROM_PAYLOAD, RED_FROM_DISPLAY_CHECK, RED_NOT_PERFORMED, NO_RED):
        assert RED_FROM_DISPLAYED_ARTIFACT != source


def test_both_photographs_are_of_the_same_code():
    """Two readings of one code, not one reading of two codes.

    Serving the same symbol at two sizes was tried and taught nothing,
    because the size it is served at never reaches the display. What the
    second photograph buys now is a second reading to compare the first
    against — which is what replaces an expectation nobody is entitled
    to write down. Two different codes could not do that.
    """
    assert len(FEASIBILITY_QR_CANDIDATES) == 2
    assert len(set(FEASIBILITY_QR_CANDIDATES)) == 1


def test_the_retired_codes_are_not_displayed_any_more():
    """They are kept as payload references, never as a display source.

    Both are cropped flush to the symbol with no quiet zone at all,
    which is why neither could be decoded. Keeping their payloads lets a
    reader identify an older run; putting either back on the display
    path would spend a window on a known answer.
    """
    assert len(RETIRED_FLUSH_CROPPED_PAYLOADS) == 2
    for payload in RETIRED_FLUSH_CROPPED_PAYLOADS:
        assert payload not in FEASIBILITY_QR_CANDIDATES
        assert not payload.startswith("https://upload.")


def test_the_span_targets_follow_from_the_module_count():
    """Derived, never carried, because the module count changed once.

    The two densities are properties of this hardware's decoder and do
    not move. The spans do: they are the densities multiplied by however
    many modules the displayed symbol has, and the displayed symbol has
    been replaced. A span written down as a number survives that
    replacement looking correct.
    """
    assert FEASIBILITY_QR_MODULES == 25
    assert required_capture_span_px(FEASIBILITY_QR_MODULES, 20) == 500
    assert required_capture_span_px(FEASIBILITY_QR_MODULES, 4) == 100
    assert QR_PX_PER_MODULE_MEASURED_PASSING == 20
    assert QR_PX_PER_MODULE_MEASURED_FAILING == 4


def test_the_known_code_is_served_from_the_host_the_demo_already_displays():
    """The displayed address is the public copy of the committed fixture.

    The code is ours and lives in this repository, so the only address it
    may be displayed from is the one this repository publishes it at.
    Anything else is a second copy whose bytes nobody here controls, and
    the digest check would refuse it at run time, on hardware, after the
    allocation was already spent.
    """
    assert FEASIBILITY_QR_URL == (
        "https://raw.githubusercontent.com/edgelens-ai/edgelens-sdk/main/"
        "examples/pytest/" + FEASIBILITY_QR.fixture
    )


def test_a_generated_payload_is_one_the_decoder_will_carry():
    for _ in range(50):
        payload = new_qr_payload()
        assert qr_payload_refusal(payload) is None
        assert len(payload) == QR_PAYLOAD_LENGTH
        assert set(payload) <= set(QR_PAYLOAD_ALPHABET)


def test_two_payloads_differ_so_a_stale_frame_cannot_pass():
    """The staleness guarantee, which is structural rather than checked.

    A photograph left over from an earlier run decodes to that run's
    payload, so the comparison fails without anything examining the
    image's age. Repeated payloads would quietly remove that, and nothing
    downstream would notice.
    """
    assert len({new_qr_payload() for _ in range(200)}) == 200


def test_the_payload_alphabet_is_inside_the_decoders_contract():
    """A widened alphabet must not be able to reach a device.

    The generator asserts its result rather than its default, so this
    checks the default itself — the one thing that assertion cannot see.
    """
    for character in QR_PAYLOAD_ALPHABET:
        assert QR_PAYLOAD_BYTE_MIN <= ord(character) <= QR_PAYLOAD_BYTE_MAX
    assert qr_payload_refusal(QR_PAYLOAD_ALPHABET) is None


def test_an_out_of_contract_payload_is_refused_where_it_is_made():
    """The trap state, stated as the scenario it prevents.

    One character outside the decoder's range is dropped before it is
    counted, and the reason goes to stderr alone. The run then reports a
    count of zero and NO_QR — byte for byte what an unlit display
    returns. So the demo would go red, the record would say the panel
    showed nothing, and the cause would be a character in our own test's
    payload. It has to be refused here, where the payload is made.
    """
    for bad in ("AB\nCD", "AB\tCD", "AB\x00CD", "ABC\x7f", "ÉABC", "AB\x1fCD"):
        refusal = qr_payload_refusal(bad)
        assert refusal is not None, bad
        assert "unlit display" in refusal

    assert qr_payload_refusal("") is not None

    # the boundaries themselves are inside the contract, and a rule that
    # excluded them would be stricter than the decoder
    assert qr_payload_refusal(chr(QR_PAYLOAD_BYTE_MIN)) is None
    assert qr_payload_refusal(chr(QR_PAYLOAD_BYTE_MAX)) is None


def test_the_generator_refuses_rather_than_returns_an_unusable_payload():
    """Widening the alphabet is a one-word edit; it must fail here.

    Passed an alphabet outside the contract, the generator must raise and
    not hand back a payload. Returning one would move the failure to the
    device, where it is indistinguishable from a dead display.
    """
    with pytest.raises(ValueError, match="unusable payload"):
        new_qr_payload(length=8, alphabet="\n")


def _decoded(payload: bytes, path: str = CAPTURE_PATH):
    """A decode record the device would have produced for one symbol."""
    stdout = (
        f"QR_DECODE_FILE {path}\n"
        "QR_DECODE_COUNT 1\n"
        f"QR_DECODE_PAYLOAD_LEN {len(payload)}\n"
        f"QR_DECODE_PAYLOAD {payload.decode('ascii')}\n"
        "QR_DECODE_STATUS DECODED\n"
    )
    return parse_qr_decode(stdout, 0)


def test_the_round_trip_passes_when_the_payload_comes_back():
    payload = new_qr_payload()
    assert round_trip_refusal(payload, _decoded(payload.encode())) is None


def test_a_stale_frame_fails_the_round_trip():
    """The failure the per-run payload exists to catch.

    A photograph of an earlier run's content decodes perfectly: the
    status is DECODED, the exit code is 0, every internal check agrees.
    The only thing wrong with it is that it is the wrong payload, and
    that is the whole reason the comparison is on content.
    """
    previous = new_qr_payload()
    current = new_qr_payload()
    refusal = round_trip_refusal(current, _decoded(previous.encode()))
    assert refusal is not None
    assert previous in refusal and current in refusal
    assert "stale" in refusal


def test_a_red_with_no_payload_says_what_it_does_and_does_not_establish():
    """NO_QR must not be reported as "the panel was dark".

    A code too small or blurred to resolve and a display with nothing on
    it return the same status and the same exit code. Naming a cause here
    would be asserting something this output cannot support, so the
    refusal has to point at the diagnostics instead.
    """
    nothing = parse_qr_decode(
        f"QR_DECODE_FILE {CAPTURE_PATH}\nQR_DECODE_COUNT 0\nQR_DECODE_STATUS NO_QR\n",
        2,
    )
    refusal = round_trip_refusal(new_qr_payload(), nothing)
    assert refusal is not None
    assert "NO_QR" in refusal
    assert "stderr" in refusal
    # it must not volunteer a cause it cannot know
    assert "dark" not in refusal.lower()


def test_an_unreadable_file_is_refused_as_its_own_finding():
    broken = parse_qr_decode(
        f"QR_DECODE_FILE {CAPTURE_PATH}\n"
        "QR_DECODE_COUNT 0\n"
        "QR_DECODE_STATUS FILE_ERROR\n",
        3,
    )
    refusal = round_trip_refusal(new_qr_payload(), broken)
    assert refusal is not None and "FILE_ERROR" in refusal


def test_a_second_symbol_in_the_frame_is_refused_rather_than_searched():
    """Accepting any matching code would pass an unexplained frame.

    The run puts one code in front of the lens. A second means the frame
    held something the demo did not display, and that is worth a red even
    when ours is among them.
    """
    wanted = new_qr_payload()
    other = new_qr_payload()
    two = parse_qr_decode(
        f"QR_DECODE_FILE {CAPTURE_PATH}\n"
        "QR_DECODE_COUNT 2\n"
        f"QR_DECODE_PAYLOAD_LEN {len(wanted)}\n"
        f"QR_DECODE_PAYLOAD {wanted}\n"
        f"QR_DECODE_PAYLOAD_LEN {len(other)}\n"
        f"QR_DECODE_PAYLOAD {other}\n"
        "QR_DECODE_STATUS DECODED\n",
        0,
    )
    refusal = round_trip_refusal(wanted, two)
    assert refusal is not None and "2 symbols" in refusal


def test_an_out_of_contract_expectation_is_reported_as_ours_not_as_a_mismatch():
    """Otherwise the reader is sent to the panel for a fault in our code."""
    refusal = round_trip_refusal("AB\nCD", _decoded(b"ABCD"))
    assert refusal is not None
    assert "this run meant to display" in refusal
    assert "nothing can be concluded" in refusal


def test_the_round_trip_compares_bytes_and_not_text():
    """A payload that differs only past the stated length must still fail.

    The decoder states its own length and the reader holds it to that, so
    the comparison is over exactly the bytes it said it read. This is the
    case where a text comparison and a byte comparison part company.
    """
    assert round_trip_refusal("ABCD", _decoded(b"ABCDE")) is not None
    assert round_trip_refusal("ABCDE", _decoded(b"ABCD")) is not None


def test_only_the_comparison_counts_as_the_demo_discriminating():
    """The distinction the deliberate-failure run exists to establish.

    Run against a display showing nothing, the demo can end red by two
    routes that are worth entirely different amounts. If the display
    reports it is showing what was asked for and the photograph then
    decodes to nothing, the comparison is what refused the run — that is
    the decode discriminating. If the display never reported it, the run
    stops before any photograph is taken, and all that has been shown is
    that the display check works.

    Both are reportable as "the demo went red", which is exactly why the
    attribution has to be made by the run rather than by whoever reads
    its output afterwards.
    """
    payload = new_qr_payload()
    dark = parse_qr_decode(
        f"QR_DECODE_FILE {CAPTURE_PATH}\nQR_DECODE_COUNT 0\nQR_DECODE_STATUS NO_QR\n",
        2,
    )
    refusal = round_trip_refusal(payload, dark)
    assert refusal is not None

    discriminating = attribute_red(True, dark, refusal)
    assert discriminating.source == RED_FROM_PAYLOAD
    assert discriminating.discriminated

    stopped_early = attribute_red(False, None, None)
    assert stopped_early.source == RED_FROM_DISPLAY_CHECK
    assert not stopped_early.discriminated
    assert "says nothing whatever about the decode" in stopped_early.reason


def test_a_run_that_never_reached_the_decoder_is_not_a_failure():
    """Not performed and failed must not be the same answer.

    A run that took no photograph the decoder ever saw has produced no
    evidence, and recording it as a failure would attribute it to the
    camera or the decoder — neither of which was reached.
    """
    not_performed = attribute_red(True, None, None)
    assert not_performed.source == RED_NOT_PERFORMED
    assert not not_performed.discriminated
    assert "not performed rather than failed" in not_performed.reason


def test_a_passing_round_trip_has_no_red_to_attribute():
    payload = new_qr_payload()
    decoded = _decoded(payload.encode())
    assert round_trip_refusal(payload, decoded) is None
    verdict = attribute_red(True, decoded, None)
    assert verdict.source == NO_RED
    assert not verdict.discriminated


def test_the_display_check_outranks_everything_after_it():
    """A red at the display check stays attributed there.

    Even with a decode in hand, a run whose display never reported the
    requested content photographed something nobody asked for. Letting a
    later failure claim the attribution would turn a verdict about the
    wrong screen into a verdict about the decode.
    """
    payload = new_qr_payload()
    stale = _decoded(new_qr_payload().encode())
    verdict = attribute_red(False, stale, round_trip_refusal(payload, stale))
    assert verdict.source == RED_FROM_DISPLAY_CHECK
    assert not verdict.discriminated


def test_qr_decode_command_marks_the_binary_runnable_and_sets_the_library_path():
    """Both halves of the one fact that costs a window if it is wrong.

    Deploy delivers the file without the executable bit, and nothing on
    the image supplies a library search path for it: no RPATH, no
    RUNPATH, no `/etc/ld-musl-*.path`, and the directory holding the
    OpenCV libraries is exported only by a profile script a non-login
    command never reads. Either omission fails with every library present
    and correct, and the capture utility's path is the one proven to work.
    """
    cmd = qr_decode_command("pw")
    assert f"chmod +x /userdata/Models/{DECODER_FILE}" in cmd
    assert "/usr/lib64:/mnt/system/lib" in cmd
    assert f"LD_LIBRARY_PATH=" in cmd.split(f"/userdata/Models/{DECODER_FILE};")[0]
    assert CAPTURE_PATH in cmd


def test_qr_decode_command_passes_exactly_one_argument():
    """Any other count is a usage error sharing a code with other causes.

    The decoder takes one path and rejects every other argument count
    with the same exit code it uses when a local resource fails, so that
    red carries no cause of its own. A second argument that looked
    harmless here would arrive as an outcome nobody can attribute.
    """
    cmd = qr_decode_command("pw")
    # anchored on the invocation, not on the chmod that names the same file
    invocation = cmd.split("LD_LIBRARY_PATH=", 1)[1]
    after_binary = invocation.split(f"/userdata/Models/{DECODER_FILE} ", 1)[1]
    args = after_binary.split("2>")[0].split()
    assert args == [CAPTURE_PATH], args


def test_qr_decode_command_does_not_echo_the_exit_code_onto_stdout():
    """The trap state, and it is not a style preference.

    Every other command here echoes `EXIT <rc>` so a reader can see it.
    The decode must not, because the reader of these records refuses any
    output following the status line — a status that is not last cannot
    be told from a report cut short in transit. An echoed code lands
    after it and fails every decode, with the device in hand and a
    session running. The code itself is not lost: it comes back as its
    own field on the exec result.
    """
    cmd = qr_decode_command("pw")
    assert 'echo "EXIT' not in cmd
    # it must still propagate, or a failed decode reads as a passing one
    assert "exit $rc" in cmd


def test_qr_decode_command_keeps_the_decoders_stderr_off_its_stdout():
    """The records and the diagnostics must arrive separable.

    A frame holding a code too small to resolve and a frame of an unlit
    panel produce identical records and the same exit code. The only
    thing that tells them apart is written to stderr, so folding the two
    streams together — which every other command here deliberately does —
    would leave the one run that can discriminate unable to.
    """
    cmd = qr_decode_command("pw")
    assert f"2> {QR_STDERR_PATH}" in cmd
    assert f'echo "{QR_DIAGNOSTICS_MARKER}"' in cmd
    # and the file is read back, or capturing it buys nothing
    assert f"cat {QR_STDERR_PATH}" in cmd
    # the decoder's own invocation must not fold its stderr into stdout
    invocation = cmd.split(f"/userdata/Models/{DECODER_FILE} ", 1)[1].split(";")[0]
    assert "2>&1" not in invocation


def test_qr_decode_command_clears_the_diagnostics_before_running():
    """Absence beforehand is what makes presence afterwards this run's.

    The decoder writes nothing to stderr on a clean decode, so an earlier
    attempt's message left at that path would be read back as this run's
    and attributed to a frame it never saw. The removal is ordered before
    the decoder runs for the same reason the capture preflight is.
    """
    cmd = qr_decode_command("pw")
    assert f"rm -f {QR_STDERR_PATH}" in cmd
    assert cmd.index(f"rm -f {QR_STDERR_PATH}") < cmd.index(
        f"chmod +x /userdata/Models/{DECODER_FILE}"
    )


def test_split_qr_output_separates_the_records_from_the_diagnostics():
    combined = (
        f"QR_DECODE_FILE {CAPTURE_PATH}\n"
        "QR_DECODE_COUNT 0\n"
        "QR_DECODE_STATUS NO_QR\n"
        f"{QR_DIAGNOSTICS_MARKER}\n"
        "qr_decode: a symbol was found but could not be read\n"
    )
    records, diagnostics = split_qr_output(combined)
    assert "QR_DECODE_STATUS NO_QR" in records
    assert QR_DIAGNOSTICS_MARKER not in records
    assert "could not be read" in diagnostics
    assert "QR_DECODE_FILE" not in diagnostics
    # the records half must still parse on its own
    decoded = parse_qr_decode(records, 2)
    assert decoded.status == QR_NO_QR


def test_split_qr_output_reports_an_empty_stderr_as_empty_not_as_missing():
    """A clean decode writes nothing to stderr, and that is not a fault."""
    combined = (
        f"QR_DECODE_FILE {CAPTURE_PATH}\n"
        "QR_DECODE_COUNT 1\n"
        "QR_DECODE_PAYLOAD_LEN 4\n"
        "QR_DECODE_PAYLOAD AB12\n"
        "QR_DECODE_STATUS DECODED\n"
        f"{QR_DIAGNOSTICS_MARKER}\n"
    )
    records, diagnostics = split_qr_output(combined)
    assert diagnostics == ""
    assert parse_qr_decode(records, 0).decoded


def test_split_qr_output_refuses_output_that_stopped_before_the_marker():
    """A truncated report must not read as a complete one with clean stderr.

    This is the trap state: without the marker there is no way to tell a
    run whose diagnostics never arrived from a run that had none, and the
    second reading is the one that would be believed.
    """
    truncated = (
        f"QR_DECODE_FILE {CAPTURE_PATH}\nQR_DECODE_COUNT 0\nQR_DECODE_STATUS NO_QR\n"
    )
    with pytest.raises(ValueError, match=QR_DIAGNOSTICS_MARKER):
        split_qr_output(truncated)


def test_split_qr_output_is_not_split_by_a_payload_holding_the_marker():
    """What is in front of the camera is not ours to assume.

    The marker is matched as a whole line, so a decoded payload that
    contains its text cannot move the boundary — which would silently
    reclassify real records as diagnostics.
    """
    combined = (
        f"QR_DECODE_FILE {CAPTURE_PATH}\n"
        "QR_DECODE_COUNT 1\n"
        f"QR_DECODE_PAYLOAD_LEN {len(QR_DIAGNOSTICS_MARKER) + 2}\n"
        f"QR_DECODE_PAYLOAD x{QR_DIAGNOSTICS_MARKER}y\n"
        "QR_DECODE_STATUS DECODED\n"
        f"{QR_DIAGNOSTICS_MARKER}\n"
    )
    records, diagnostics = split_qr_output(combined)
    assert "QR_DECODE_STATUS DECODED" in records
    assert diagnostics == ""
    decoded = parse_qr_decode(records, 0)
    assert decoded.codes[0].payload == f"x{QR_DIAGNOSTICS_MARKER}y".encode()


def test_preflight_removes_every_path_a_run_writes():
    cmd = preflight_command("pw")
    assert f"rm -f {CAPTURE_PATH}" in cmd
    assert f"rm -f {RESULT_PATH}" in cmd
    assert f"rm -f {capture_manifest_path()}" in cmd


def test_preflight_clears_the_burst_by_pattern_not_by_the_settled_frames_name():
    """The failure this is written against, stated as a scenario.

    A run writes the settled frame plus a burst beside it. If the preflight
    removed only the settled frame's own name, an earlier run's burst would
    survive, and this run would then report frames that are real images
    with sizes and digests that agree — from the wrong run. Nothing later
    in the test could tell. So the pattern has to be what is cleared, and
    removing the exact name is not a substitute for it.
    """
    cmd = preflight_command("pw")
    glob = capture_series_glob()
    assert glob != CAPTURE_PATH
    assert f"rm -f {glob}" in cmd
    # and the sweep must report the pattern empty, not merely run
    assert f'echo "ABSENT_GLOB {glob}"' in cmd


def test_the_burst_pattern_matches_what_the_capture_run_writes():
    stem = capture_stem()
    glob = capture_series_glob()
    assert stem == "/userdata/Models/capture"
    assert glob == "/userdata/Models/capture.f*.jpg"
    assert capture_manifest_path() == "/userdata/Models/capture.manifest.txt"
    for name in ("capture.f000.jpg", "capture.f013.jpg"):
        assert fnmatch.fnmatch(f"/userdata/Models/{name}", glob)
    # the settled frame is not part of the burst pattern: it is cleared by
    # name, and a pattern that swallowed it would hide a missing exact rm
    assert not fnmatch.fnmatch(CAPTURE_PATH, glob)


def test_capture_command_passes_no_frame_schedule():
    """The schedule belongs to the capture utility and is not copied here.

    A value that exists in two places is one that can drift, and the run
    echoes the schedule it used, so there is nothing this example needs to
    hold. The test is written against the shape of a regression: anything
    that looks like a schedule being passed after the output path.
    """
    cmd = capture_command("pw")
    after = cmd.split(CAPTURE_PATH, 1)[1]
    assert "," not in after.split(";")[0]


def test_capture_output_paths_covers_the_exact_set_and_the_pattern():
    exact, glob = capture_output_paths()
    assert set(exact) == {CAPTURE_PATH, capture_manifest_path(), RESULT_PATH}
    assert glob == capture_series_glob()


def test_one_listing_measures_every_path_and_hashes_only_the_fetched():
    """Both answers in one call, because nothing makes them two.

    Which images come back is decided from the sizes already on the
    capture run's stdout, so the hash set is known before anything is
    measured. A second command would spend a share of a shared per-host
    request budget to learn what the first could have said.
    """
    measured = "/userdata/Models/capture.f004.jpg"
    hashed = "/userdata/Models/capture.jpg"
    cmd = listing_command("pw", [measured, hashed], [hashed])
    assert f"wc -c < {measured}" in cmd
    assert f"wc -c < {hashed}" in cmd
    assert f"sha256sum {hashed}" in cmd
    assert f"sha256sum {measured}" not in cmd


def test_the_listing_quotes_paths_that_came_from_the_device():
    """Reported paths are device-controlled and reach a root shell.

    The password and the command body are already quoted; leaving the
    paths out of that would be the one gap in an otherwise closed
    discipline. A separator in a path clears the record pattern (which
    only excludes whitespace) and the clearing glob (where `*` matches it
    happily), so neither gate in front of this one stops it.
    """
    nasty = "/userdata/Models/capture.f0;touch CLAIMED.jpg"
    cmd = listing_command("pw", [nasty], [nasty])

    # Tokenise the way a shell would, rather than looking for substrings:
    # the correctly quoted form *contains* the dangerous text, so its
    # presence proves nothing either way. What matters is whether the
    # path survives as one word or breaks into a second command.
    body = shlex.split(cmd.split("sh -c ", 1)[1].rsplit(" 2>&1", 1)[0])[0]
    tokens = shlex.split(body)
    assert nasty in tokens
    assert "touch" not in tokens
    assert "CLAIMED.jpg" not in tokens


def test_the_fetch_quotes_the_path_too():
    nasty = "/userdata/Models/capture.f0;id.jpg"
    assert shlex.quote(nasty) in fetch_chunk_command("pw", nasty, 0, 16)


def test_parse_sizes_reads_the_hashed_lines_as_well():
    """One listing emits two line shapes and the sizes span both.

    A reader that looked at only the measured-only shape would return
    sizes for part of the set, and the short-write check would then pass
    by having nothing to compare for the rest — a check that cannot fail
    for most of its inputs.
    """
    sha = "b" * 64
    out = parse_sizes(
        "SIZE 35314 PATH /userdata/Models/capture.f000.jpg\n"
        f"SIZE 241190 SHA256 {sha} PATH /userdata/Models/capture.jpg\n"
    )
    assert out == {
        "/userdata/Models/capture.f000.jpg": 35314,
        "/userdata/Models/capture.jpg": 241190,
    }


def test_fetch_chunk_requests_an_exact_byte_range():
    cmd = fetch_chunk_command("pw", "/userdata/Models/result.jpg", 4096, 1024)
    assert "skip=4096" in cmd
    assert "count=1024" in cmd
    assert "base64" in cmd


# --- stat / absence parsing ------------------------------------------------


def test_parse_stat_reads_size_and_digest():
    sha = "a" * 64
    size, digest = parse_stat(f"Password: \nEXIT 0\nSIZE 12345 SHA256 {sha}\n")
    assert (size, digest) == (12345, sha)


def test_parse_stat_raises_when_the_device_reports_no_file():
    with pytest.raises(FileNotFoundError):
        parse_stat("EXIT 1\nABSENT /userdata/Models/capture.jpg\n")


def test_parse_stat_raises_when_nothing_was_reported():
    with pytest.raises(ValueError):
        parse_stat("Password: \nsome unrelated output\n")


def test_parse_absent_lists_the_paths_proved_gone():
    out = (
        f"WRITABLE /userdata/Models\n"
        f"ABSENT {CAPTURE_PATH}\nABSENT {RESULT_PATH}\n"
    )
    assert parse_absent(out) == [CAPTURE_PATH, RESULT_PATH]


def test_parse_absent_omits_a_path_that_survived():
    out = f"PRESENT {CAPTURE_PATH} SHA256 {'b' * 64}\nABSENT {RESULT_PATH}\n"
    assert parse_absent(out) == [RESULT_PATH]


# --- chunk decoding --------------------------------------------------------


def test_decode_chunk_round_trips_and_ignores_the_password_echo():
    raw = bytes(range(256)) * 4
    # Verbatim shape from a live camera: `base64` wraps at 76 columns, and the
    # sudo prompt has no trailing newline, so it arrives glued to the first
    # payload line rather than sitting on one of its own.
    wrapped = textwrap.wrap(base64.b64encode(raw).decode(), 76)
    stdout = "Password: " + "\n".join(wrapped) + "\n"
    assert decode_chunk(stdout) == raw
    assert hashlib.sha256(decode_chunk(stdout)).hexdigest() == (
        hashlib.sha256(raw).hexdigest()
    )


def test_decode_chunk_refuses_a_truncated_stream():
    stdout = base64.b64encode(b"x" * 64).decode() + "\n[output truncated at 256KiB]"
    with pytest.raises(ValueError):
        decode_chunk(stdout)


# --- jpeg dimensions -------------------------------------------------------


def test_jpeg_dimensions_reads_the_bundled_sample():
    data = (models_dir() / "sample_faces.jpg").read_bytes()
    width, height = jpeg_dimensions(data)
    assert width > 0 and height > 0


# --- is there a picture of anything here ------------------------------------
#
# Both numbers below are measurements, not fixtures. The blank one is the frame
# a real run returned after photographing an unlit screen; the other is the
# annotated reference frame in models/, same size, same pipeline. The threshold
# has to separate exactly these two, so they are the test.


def test_the_frame_from_the_unlit_screen_is_classified_blank():
    """15605 bytes over the anchor size — what a run actually returned.

    It is not a tiny file: there were three annotation boxes drawn on it and
    the usual JPEG overhead. A bar set by file size alone, or a threshold
    guessed an order of magnitude lower, passes this frame.
    """
    assert bits_per_pixel(15605, *ANCHOR_FRAME_SIZE) < BLANK_BITS_PER_PIXEL


def test_a_real_annotated_frame_is_not_classified_blank():
    data = (models_dir() / "sample_faces_detected.jpg").read_bytes()
    width, height = jpeg_dimensions(data)
    assert bits_per_pixel(len(data), width, height) >= BLANK_BITS_PER_PIXEL


def test_the_reference_anchor_is_the_size_the_threshold_was_measured_at():
    """Otherwise the margin below is measured against a different question.

    The threshold is per-pixel, so replacing this image with one of another
    size would change what every test here means while they all kept passing.
    """
    data = (models_dir() / "sample_faces_detected.jpg").read_bytes()
    assert jpeg_dimensions(data) == ANCHOR_FRAME_SIZE


def test_the_threshold_keeps_real_margin_on_both_sides():
    """A threshold wedged against either anchor would flap run to run."""
    data = (models_dir() / "sample_faces_detected.jpg").read_bytes()
    width, height = jpeg_dimensions(data)
    blank = bits_per_pixel(15605, *ANCHOR_FRAME_SIZE)
    real = bits_per_pixel(len(data), width, height)
    assert BLANK_BITS_PER_PIXEL >= blank * 2
    assert BLANK_BITS_PER_PIXEL <= real / 2


def test_the_measure_does_not_carry_across_frame_sizes():
    """Why the run checks geometry before applying the threshold.

    The same bytes of real detail, scored at a larger frame size, fall under
    the threshold — indistinguishable from the blank frame above. This is the
    limitation the end-to-end test guards against, not a property to rely on.
    """
    real = (models_dir() / "sample_faces_detected.jpg").read_bytes()
    assert bits_per_pixel(len(real), *ANCHOR_FRAME_SIZE) >= BLANK_BITS_PER_PIXEL
    assert bits_per_pixel(len(real), 1920, 1080) < BLANK_BITS_PER_PIXEL


def test_bits_per_pixel_refuses_dimensions_it_cannot_divide_by():
    with pytest.raises(ValueError):
        bits_per_pixel(1000, 0, 480)


def test_display_image_is_public_and_not_ours():
    """Lint the displayed-image constant in this example.

    This guards ``DISPLAY_IMAGE_URL`` against a future edit that points the
    demo at something only this machine can fetch. It is not validation of
    customer input — nothing here is supplied by a caller — so it cannot
    fail for any URL that would survive review of this file.

    Your device fetches the URL itself, so the host has to resolve from
    wherever your device is and has to match the certificate it serves. An
    address literal fails both: one that only resolves on a single network
    is unreachable from anywhere else, and https to a bare address cannot
    match a certificate issued for a name. The check is on the string
    alone and performs no DNS lookup, so it stays usable offline.
    """
    from demo_inference import DISPLAY_IMAGE_URL

    parsed = urllib.parse.urlsplit(DISPLAY_IMAGE_URL)
    assert parsed.scheme == "https"

    host = parsed.hostname
    assert host, f"no host in {DISPLAY_IMAGE_URL!r}"
    assert host != "localhost"
    assert not host.endswith((".local", ".localhost", ".internal"))

    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass  # A hostname, which is what a publicly fetchable URL wants.
    else:
        pytest.fail(f"{host} is an address literal, not a public hostname")


def test_jpeg_dimensions_rejects_non_jpeg_bytes():
    with pytest.raises(ValueError):
        jpeg_dimensions(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)


# --- what the capture run reports ------------------------------------------
#
# The records below are the only description of a run that survives the
# device being wiped, so the parser's job is less about reading a good one
# than about refusing a damaged one. Every rejected shape in the table
# further down would otherwise read as a *smaller but successful* run —
# fewer frames taken, rather than a report that cannot be trusted — and
# that is the wrong answer which looks most like a right one.
#
# A rejection predicate with no table of inputs it must reject has not been
# tested. A suite full of accepted inputs passes either way.

GOOD_CAPTURE = textwrap.dedent(
    """\
    Password: SCHEDULE n=4 indices=0,1,4,8
    CAPTURE path=/userdata/Models/capture.f000.jpg frame=0 elapsed_ms=0 bytes=35314
    CAPTURE path=/userdata/Models/capture.f001.jpg frame=1 elapsed_ms=33 bytes=36002
    CAPTURE path=/userdata/Models/capture.f004.jpg frame=4 elapsed_ms=133 bytes=180244
    CAPTURE path=/userdata/Models/capture.f008.jpg frame=8 elapsed_ms=266 bytes=241190
    SETTLED path=/userdata/Models/capture.jpg frame=8
    STATUS COMPLETE
    EXIT 0
    """
)


def test_parses_the_schedule_the_device_reported_using():
    report = parse_capture_report(GOOD_CAPTURE)
    assert report.schedule == (0, 1, 4, 8)
    assert report.complete
    assert len(report.frames) == 4


def test_the_schedule_is_read_and_never_asserted_against_a_local_copy():
    """A shorter or longer burst must parse without complaint.

    The capture utility owns the schedule, so a change to it is not a
    failure here. Asserting its contents would put back the second copy
    this example deliberately does not keep.
    """
    longer = GOOD_CAPTURE.replace("n=4 indices=0,1,4,8", "n=4 indices=0,2,9,30")
    assert parse_capture_report(longer).schedule == (0, 2, 9, 30)


def test_frame_records_carry_the_timing_and_the_size():
    report = parse_capture_report(GOOD_CAPTURE)
    first = report.frame_at(0)
    assert (first.elapsed_ms, first.size_bytes) == (0, 35314)
    assert [f.frame for f in report.in_order()] == [0, 1, 4, 8]


def test_the_settled_frame_is_read_from_its_record_not_from_position():
    """Reordered records must not change which frame is the settled one.

    Last line, highest index and last scheduled entry all agree with the
    record on a healthy run, which is exactly what makes them dangerous:
    they are right until the run where they are not, and that run is the
    one that matters.
    """
    lines = GOOD_CAPTURE.strip().splitlines()
    settled = lines.pop(5)
    reordered = "\n".join([lines[0], settled] + lines[1:]) + "\n"
    report = parse_capture_report(reordered)
    assert report.settled_frame == 8
    assert report.settled_path == "/userdata/Models/capture.jpg"


# The rejection table. Each entry is a real damage mode, and the comment
# says what it would look like if it were accepted instead.
BAD_CAPTURES = {
    # a record cut off mid-field: would read as a frame never taken
    "truncated record": GOOD_CAPTURE.replace(
        "frame=4 elapsed_ms=133 bytes=180244", "frame=4 elapsed_ms=13"
    ),
    # no byte count: the short-write check silently has nothing to compare
    "missing bytes field": GOOD_CAPTURE.replace(
        " bytes=36002", ""
    ),
    # no timing: the measurement this run exists for is gone from that frame
    "missing elapsed_ms field": GOOD_CAPTURE.replace(
        " elapsed_ms=133", ""
    ),
    # two records for one frame: a frame counted twice looks like a full burst
    "duplicate frame index": GOOD_CAPTURE.replace(
        "frame=4 elapsed_ms=133", "frame=1 elapsed_ms=133"
    ),
    # two records at one path: the second would overwrite the first in place
    "duplicate path": GOOD_CAPTURE.replace(
        "capture.f004.jpg frame=4", "capture.f001.jpg frame=4"
    ),
    # a status nobody has defined: would be treated as neither pass nor fail
    "unknown status": GOOD_CAPTURE.replace("STATUS COMPLETE", "STATUS FINE"),
    # success claimed with no settled frame named: which image is the
    # inference input becomes a guess
    "complete without a settled record": GOOD_CAPTURE.replace(
        "SETTLED path=/userdata/Models/capture.jpg frame=8\n", ""
    ),
    # the settled frame names an index that was never captured
    "settled frame has no record": GOOD_CAPTURE.replace(
        "capture.jpg frame=8", "capture.jpg frame=9"
    ),
    # success claimed with fewer frames than the schedule it echoed
    "complete with a frame missing": GOOD_CAPTURE.replace(
        "CAPTURE path=/userdata/Models/capture.f001.jpg frame=1 elapsed_ms=33 bytes=36002\n",
        "",
    ),
    # the echoed count disagrees with the echoed list
    "schedule count disagrees with the indices": GOOD_CAPTURE.replace(
        "n=4 indices=0,1,4,8", "n=6 indices=0,1,4,8"
    ),
    # the immediate frame absent: the comparison the burst exists for is gone
    "first scheduled frame missing": GOOD_CAPTURE.replace(
        "CAPTURE path=/userdata/Models/capture.f000.jpg frame=0 elapsed_ms=0 bytes=35314",
        "CAPTURE path=/userdata/Models/capture.f002.jpg frame=2 elapsed_ms=66 bytes=35314",
    ),
    # two status lines: whichever is read first decides the verdict
    "two status lines": GOOD_CAPTURE.replace(
        "STATUS COMPLETE", "STATUS COMPLETE\nSTATUS INCOMPLETE_NO_FRAMES"
    ),
    # nothing at all
    "empty output": "",
    # the binary ran but reported nothing parseable
    "no records": "Password: \nsh: capture_jpeg: not found\nEXIT 127\n",
}


@pytest.mark.parametrize("name", sorted(BAD_CAPTURES))
def test_damaged_capture_reports_are_refused(name):
    with pytest.raises((ValueError, FileNotFoundError)):
        parse_capture_report(BAD_CAPTURES[name])


def test_the_rejection_table_is_tested_against_an_input_that_passes():
    """The positive control for the table above.

    Without it a parser that refused everything would satisfy every entry
    in the table and look thoroughly tested.
    """
    assert parse_capture_report(GOOD_CAPTURE).complete


def test_an_incomplete_run_parses_so_its_frames_can_still_be_collected():
    """A failed run's records must survive parsing, not abort it.

    The capture utility keeps its frames and records when it fails, which
    is only useful if they can be read. Refusing to parse an incomplete
    report would throw away the evidence of the failure along with it.
    """
    partial = (
        "SCHEDULE n=4 indices=0,1,4,8\n"
        "CAPTURE path=/userdata/Models/capture.f000.jpg frame=0 elapsed_ms=0 bytes=35314\n"
        "CAPTURE path=/userdata/Models/capture.f001.jpg frame=1 elapsed_ms=33 bytes=35401\n"
        "STATUS INCOMPLETE_NOT_SETTLED\n"
    )
    report = parse_capture_report(partial)
    assert not report.complete
    assert report.status == "INCOMPLETE_NOT_SETTLED"
    assert len(report.frames) == 2
    assert report.settled_path is None


def test_no_frames_is_a_different_finding_from_none_settled():
    none_arrived = "SCHEDULE n=4 indices=0,1,4,8\nSTATUS INCOMPLETE_NO_FRAMES\n"
    report = parse_capture_report(none_arrived)
    assert report.status == "INCOMPLETE_NO_FRAMES"
    assert report.frames == ()


# --- the reported paths must be ones the preflight cleared ------------------


def test_a_reported_path_the_preflight_never_cleared_is_caught():
    """The stale-frame case, which nothing about the file would reveal.

    A frame at a path that was never cleared may be left over from an
    earlier run. It is a real image, its size agrees with its record and
    its digest matches — every later check passes. This is the only point
    at which the difference is still visible.
    """
    report = parse_capture_report(GOOD_CAPTURE)
    cleared_exact = [CAPTURE_PATH, RESULT_PATH, capture_manifest_path()]
    assert paths_not_cleared(report, cleared_exact, [capture_series_glob()]) == ()
    # the same report against a preflight that cleared only the exact names
    stale = paths_not_cleared(report, cleared_exact, [])
    assert len(stale) == 4
    assert all(".f0" in p for p in stale)


def test_the_settled_frame_counts_as_a_path_that_must_be_cleared():
    report = parse_capture_report(GOOD_CAPTURE)
    missed = paths_not_cleared(report, [RESULT_PATH], [capture_series_glob()])
    assert missed == (CAPTURE_PATH,)


# --- the writer's count against the file on disk ----------------------------


def test_a_short_write_is_caught_by_comparing_the_two_counts():
    report = parse_capture_report(GOOD_CAPTURE)
    on_disk = {f.path: f.size_bytes for f in report.frames}
    assert size_disagreements(report, on_disk) == ()
    on_disk["/userdata/Models/capture.f004.jpg"] = 90000
    assert size_disagreements(report, on_disk) == (
        ("/userdata/Models/capture.f004.jpg", 180244, 90000),
    )


def test_a_path_that_was_not_measured_is_not_reported_as_a_disagreement():
    """Absence of a measurement is not evidence of a mismatch.

    Which is why it is caught by a different predicate — see the coverage
    test below. This one deliberately stays silent so that "no size" and
    "wrong size" cannot be confused for one another.
    """
    report = parse_capture_report(GOOD_CAPTURE)
    assert size_disagreements(report, {}) == ()


def test_a_reported_path_with_no_measured_size_is_a_failure_not_a_skip():
    """The denominator for the short-write check.

    `size_disagreements` can only disagree about a path it was given a
    size for, so on its own it is satisfied by a listing that measured
    almost nothing: fewer measurements mean fewer disagreements. That is
    the shape of a check that passes for most of its inputs by never
    running on them. Coverage is what makes the comparison mean
    something, and it must be its own assertion.
    """
    report = parse_capture_report(GOOD_CAPTURE)
    claimed = [f.path for f in report.frames] + [CAPTURE_PATH]
    full = {f.path: f.size_bytes for f in report.frames}
    full[CAPTURE_PATH] = report.frame_at(report.settled_frame).size_bytes
    assert unmeasured_paths(claimed, full) == ()
    assert size_disagreements(report, full) == ()

    # the exact failure: everything measured except one frame, and the
    # size comparison stays silent about it
    partial = {p: v for p, v in full.items() if "f004" not in p}
    assert unmeasured_paths(claimed, partial) == (
        "/userdata/Models/capture.f004.jpg",
    )
    assert size_disagreements(report, partial) == ()


def test_a_listing_that_measured_nothing_is_caught_by_coverage_alone():
    report = parse_capture_report(GOOD_CAPTURE)
    claimed = [f.path for f in report.frames]
    assert len(unmeasured_paths(claimed, {})) == len(claimed)


def test_a_frame_that_arrives_short_is_caught_against_the_cameras_own_count():
    """The third count, and the only one involving what the camera said.

    The digest compares the arrival against the listing, and both of
    those measure the file as it exists now. Comparing the arrival
    against the record is the only check that brings the camera's own
    account of the write into it.
    """
    report = parse_capture_report(GOOD_CAPTURE)
    full = {f.path: f.size_bytes for f in report.frames}
    assert fetched_length_disagreements(report, full) == ()
    full["/userdata/Models/capture.f008.jpg"] = 120000
    assert fetched_length_disagreements(report, full) == (
        ("/userdata/Models/capture.f008.jpg", 241190, 120000),
    )


def test_an_unfetched_frame_is_not_reported_as_arriving_short():
    report = parse_capture_report(GOOD_CAPTURE)
    assert fetched_length_disagreements(report, {}) == ()


def test_the_three_counts_are_distinct_predicates():
    """Collapsing any two of them is a regression however tidy it looks.

    Writer accounting, an independent on-disk measurement, and the local
    digest of the bytes that arrived answer three different questions.
    Here the file is intact on the device and the transfer lost bytes:
    the on-disk comparison is silent and the arrival comparison fires. A
    single merged check would have to pick one of those behaviours.
    """
    report = parse_capture_report(GOOD_CAPTURE)
    intact_on_device = {f.path: f.size_bytes for f in report.frames}
    truncated_in_transit = dict(intact_on_device)
    truncated_in_transit["/userdata/Models/capture.f004.jpg"] = 90000
    assert size_disagreements(report, intact_on_device) == ()
    assert len(fetched_length_disagreements(report, truncated_in_transit)) == 1


# --- a failed run must still give up its evidence ----------------------------


def test_an_incomplete_run_still_yields_a_non_empty_fetch_set():
    """Fetch-then-fail, shown rather than asserted to exist.

    The capture utility keeps its frames on a failed run on purpose. The
    test fails afterwards — but if it failed *first*, the frames would
    stay on a device that is released minutes later, and the evidence of
    the failure would be discarded at the one moment it is the only
    evidence there is.
    """
    partial = (
        "SCHEDULE n=4 indices=0,1,4,8\n"
        "CAPTURE path=/userdata/Models/capture.f000.jpg frame=0 "
        "elapsed_ms=0 bytes=35314\n"
        "CAPTURE path=/userdata/Models/capture.f001.jpg frame=1 "
        "elapsed_ms=33 bytes=180900\n"
        "STATUS INCOMPLETE_NOT_SETTLED\n"
    )
    report = parse_capture_report(partial)
    plan = plan_capture_fetch(report)

    # the run has failed ...
    assert not report.complete
    assert report.settled_path is None
    # ... and there is still something to bring back, and it is accounted for
    assert plan.fetch
    assert "/userdata/Models/capture.f000.jpg" in plan.fetch
    assert plan.accounts_for(report)
    # the knee is still found, so the partial curve is still a measurement
    assert plan.knee_frame == 1


def test_a_run_with_no_frames_has_nothing_to_fetch_and_still_accounts():
    none_arrived = "SCHEDULE n=4 indices=0,1,4,8\nSTATUS INCOMPLETE_NO_FRAMES\n"
    report = parse_capture_report(none_arrived)
    plan = plan_capture_fetch(report)
    assert plan.fetch == ()
    assert plan.skipped == ()
    assert plan.accounts_for(report)


# --- the account that outlives the device -----------------------------------


def test_the_account_records_why_each_frame_was_not_fetched():
    """The reasons have to be in the file, not only in the test output.

    The device is wiped minutes after the run. A frame left behind on
    purpose and a frame nobody noticed look identical from then on, and
    the reason column is the whole difference.
    """
    report = parse_capture_report(GOOD_CAPTURE)
    plan = plan_capture_fetch(report)
    table = accounting_table(report, plan)

    for f in report.frames:
        assert f.path in table
        assert str(f.elapsed_ms) in table
        assert str(f.size_bytes) in table
    assert report.status in table
    assert "indices=0,1,4,8" in table
    # every skipped frame appears with a non-empty reason on its own row
    for path, reason in plan.skipped:
        row = next(line for line in table.splitlines() if path in line)
        assert "\tno\t" in row
        assert reason.split(":")[0][:12] in row
    # and a fetched frame is marked as fetched
    first = "/userdata/Models/capture.f000.jpg"
    row = next(line for line in table.splitlines() if first in line)
    assert "\tyes\t" in row


def test_the_account_survives_an_incomplete_run():
    partial = (
        "SCHEDULE n=4 indices=0,1,4,8\n"
        "CAPTURE path=/userdata/Models/capture.f000.jpg frame=0 "
        "elapsed_ms=0 bytes=35314\n"
        "STATUS INCOMPLETE_NO_FRAMES\n"
    )
    report = parse_capture_report(partial)
    table = accounting_table(report, plan_capture_fetch(report))
    assert "INCOMPLETE_NO_FRAMES" in table
    assert "/userdata/Models/capture.f000.jpg" in table


# --- which images come back -------------------------------------------------


def test_the_plan_brings_back_the_first_and_settled_frames_and_brackets_the_rise():
    report = parse_capture_report(GOOD_CAPTURE)
    plan = plan_capture_fetch(report)
    assert "/userdata/Models/capture.f000.jpg" in plan.fetch
    assert CAPTURE_PATH in plan.fetch
    # f001 -> f004 is the first jump past the ratio, so that pair brackets it
    assert plan.knee_frame == 4
    assert "/userdata/Models/capture.f001.jpg" in plan.fetch
    assert len(plan.fetch) <= FETCH_IMAGE_BOUND


def test_the_plan_accounts_for_every_reported_frame():
    """Fetched or skipped-with-a-reason; silence about a frame is the bug.

    A frame left on the device on purpose and a frame nobody noticed look
    identical once the device is released, and only one of them is a
    result.
    """
    report = parse_capture_report(GOOD_CAPTURE)
    plan = plan_capture_fetch(report)
    assert plan.accounts_for(report)
    assert all(reason for _, reason in plan.skipped)


def test_the_bound_holds_however_long_the_burst_is():
    """A longer burst must cost device time and never transfer."""
    frames = "".join(
        f"CAPTURE path=/userdata/Models/capture.f{i:03d}.jpg frame={i} "
        f"elapsed_ms={i * 33} bytes={35000 + i}\n"
        for i in range(40)
    )
    long_run = (
        "SCHEDULE n=40 indices=" + ",".join(str(i) for i in range(40)) + "\n"
        + frames
        + "SETTLED path=/userdata/Models/capture.jpg frame=39\n"
        + "STATUS COMPLETE\n"
    )
    report = parse_capture_report(long_run)
    plan = plan_capture_fetch(report)
    assert len(plan.fetch) <= FETCH_IMAGE_BOUND
    assert plan.accounts_for(report)
    assert len(plan.skipped) == 39


def test_a_burst_that_never_gains_detail_selects_no_extra_images():
    """The degenerate curve, which is the finding this run looks for.

    Every frame compressing to about the same size as the one taken
    immediately means nothing in the burst carries more detail than the
    first. There is no rise to bracket, so no extra image is worth
    bringing back — and the flat curve has to be reported as a result
    rather than passing quietly as "two images, fine".
    """
    flat = GOOD_CAPTURE.replace("bytes=180244", "bytes=35500").replace(
        "bytes=241190", "bytes=35610"
    )
    report = parse_capture_report(flat)
    plan = plan_capture_fetch(report)
    assert plan.knee_frame is None
    assert set(plan.fetch) == {"/userdata/Models/capture.f000.jpg", CAPTURE_PATH}
    assert plan.accounts_for(report)


def test_a_single_record_selects_only_itself_and_still_accounts():
    one = (
        "SCHEDULE n=1 indices=0\n"
        "CAPTURE path=/userdata/Models/capture.f000.jpg frame=0 "
        "elapsed_ms=0 bytes=35314\n"
        "SETTLED path=/userdata/Models/capture.jpg frame=0\n"
        "STATUS COMPLETE\n"
    )
    report = parse_capture_report(one)
    plan = plan_capture_fetch(report)
    assert plan.knee_frame is None
    assert plan.accounts_for(report)
    assert CAPTURE_PATH in plan.fetch


def test_a_curve_that_rises_at_f000_finds_no_knee_and_says_so():
    """The selector's own version of the trap it exists to catch.

    `f000` is the baseline, so the comparison can never fire on it: a
    burst whose detail is already there in the immediate frame reaches
    "no knee" by a route indistinguishable from a flat near-black burst.
    Same `knee_frame is None`, same reported finding, two completely
    different facts about the hardware — one is a camera that needs no
    settling, the other is a camera seeing nothing at all. The images are
    what separate them, which is why both of them still bring back the
    first and the settled frame.
    """
    high = GOOD_CAPTURE.replace("bytes=35314", "bytes=240000").replace(
        "bytes=36002", "bytes=240500"
    )
    report = parse_capture_report(high)
    plan = plan_capture_fetch(report)
    assert plan.knee_frame is None
    assert "/userdata/Models/capture.f000.jpg" in plan.fetch
    assert CAPTURE_PATH in plan.fetch
    assert plan.accounts_for(report)
    # and it is NOT the flat case: the first frame is already detailed
    assert report.frame_at(0).size_bytes > 200000


def test_the_knee_is_the_first_rise_and_not_the_largest_frame():
    """Where detail starts is the question, not where it peaks."""
    rising = GOOD_CAPTURE.replace("bytes=36002", "bytes=200000").replace(
        "bytes=180244", "bytes=900000"
    )
    report = parse_capture_report(rising)
    plan = plan_capture_fetch(report)
    assert plan.knee_frame == 1
    assert KNEE_BYTES_RATIO * report.frame_at(0).size_bytes < 200000


def test_the_settled_frames_own_burst_copy_is_not_fetched_twice():
    report = parse_capture_report(GOOD_CAPTURE)
    plan = plan_capture_fetch(report)
    assert "/userdata/Models/capture.f008.jpg" not in plan.fetch
    reasons = dict(plan.skipped)
    assert "settled frame" in reasons["/userdata/Models/capture.f008.jpg"]


# --- the size and digest listings -------------------------------------------


def test_parse_sizes_reads_every_path():
    out = parse_sizes(
        "SIZE 35314 PATH /userdata/Models/capture.f000.jpg\n"
        "SIZE 241190 PATH /userdata/Models/capture.jpg\n"
    )
    assert out == {
        "/userdata/Models/capture.f000.jpg": 35314,
        "/userdata/Models/capture.jpg": 241190,
    }


def test_parse_sizes_raises_when_a_path_is_missing():
    with pytest.raises(FileNotFoundError):
        parse_sizes("SIZE 35314 PATH /a.jpg\nABSENT /b.jpg\n")


def test_parse_sizes_raises_when_nothing_was_measured():
    with pytest.raises(ValueError):
        parse_sizes("Password: \n")


def test_parse_digests_pairs_each_path_with_its_size_and_digest():
    sha = "a" * 64
    out = parse_digests(f"SIZE 241190 SHA256 {sha} PATH /userdata/Models/capture.jpg\n")
    assert out == {"/userdata/Models/capture.jpg": (241190, sha)}


def test_parse_digests_raises_when_a_path_is_missing():
    with pytest.raises(FileNotFoundError):
        parse_digests("ABSENT /userdata/Models/capture.jpg\n")


def test_a_size_only_line_is_not_read_as_a_digest_line():
    """The two listings must not be confusable for one another.

    They answer different questions — what the file measures, and whether
    the bytes that arrived are the bytes on the device — and a parser that
    accepted either for both would collapse the independence that makes
    the second check worth running.
    """
    with pytest.raises(ValueError):
        parse_digests("SIZE 35314 PATH /userdata/Models/capture.f000.jpg\n")


def test_absent_globs_are_parsed_separately_from_absent_paths():
    out = (
        "ABSENT /userdata/Models/capture.jpg\n"
        "ABSENT_GLOB /userdata/Models/capture.f*.jpg\n"
    )
    assert parse_absent(out) == ["/userdata/Models/capture.jpg"]
    assert parse_absent_globs(out) == ["/userdata/Models/capture.f*.jpg"]


# ---- reading a QR out of a photograph ---------------------------------------
#
# The decoder runs on the device, over a frame the camera took. These
# exercise the host side of that: what its report means, and every way a
# report can be wrong while still looking like an answer.

CAPTURE = "/userdata/Models/capture.jpg"
NONCE = b"edgelens-7f3c91a04e2b"


def decoded(payload: bytes = NONCE, path: str = CAPTURE, count: int = 1) -> str:
    lines = [f"QR_DECODE_FILE {path}", f"QR_DECODE_COUNT {count}"]
    for _ in range(count):
        lines.append(f"QR_DECODE_PAYLOAD_LEN {len(payload)}")
        lines.append(f"QR_DECODE_PAYLOAD {payload.decode()}")
    lines.append(f"QR_DECODE_STATUS {QR_DECODED}")
    return "\n".join(lines) + "\n"


def without_a_symbol(status: str, path: str = CAPTURE) -> str:
    return (
        f"QR_DECODE_FILE {path}\n"
        f"QR_DECODE_COUNT 0\n"
        f"QR_DECODE_STATUS {status}\n"
    )


def test_a_decoded_symbol_comes_back_as_bytes_with_the_length_the_decoder_declared():
    d = parse_qr_decode(decoded(), 0)
    assert d.decoded
    assert d.path == CAPTURE
    assert [(c.payload_len, c.payload) for c in d.codes] == [(len(NONCE), NONCE)]


def test_a_readable_frame_with_no_symbol_in_it_is_its_own_outcome():
    d = parse_qr_decode(without_a_symbol(QR_NO_QR), 2)
    assert d.status == QR_NO_QR
    assert not d.decoded
    assert d.codes == ()


def test_a_file_that_could_not_be_read_is_a_different_outcome_from_an_empty_frame():
    d = parse_qr_decode(without_a_symbol(QR_FILE_ERROR, "/userdata/Models/absent.jpg"), 3)
    assert d.status == QR_FILE_ERROR
    assert d.path == "/userdata/Models/absent.jpg"
    assert d.codes == ()


def test_each_status_arrives_with_exactly_one_exit_code_and_the_table_is_the_contract():
    """The two halves of the outcome, pinned against each other.

    Everything else here rests on this table, so it is asserted rather
    than trusted: three outcomes, three codes, and the usage code sharing
    with none of them. A usage error means the decoder never looked at an
    image, so folding it in with "nothing was found" would be the same
    collapse this whole mechanism exists to refuse, one level up.
    """
    assert set(QR_EXIT_STATUS.values()) == {QR_DECODED, QR_NO_QR, QR_FILE_ERROR}
    assert len(QR_EXIT_STATUS) == 3
    assert QR_EXIT_NO_OUTCOME not in QR_EXIT_STATUS


@pytest.mark.parametrize("code,status", sorted(QR_EXIT_STATUS.items()))
def test_every_documented_exit_code_parses_when_its_status_agrees(code, status):
    out = decoded() if status == QR_DECODED else without_a_symbol(status)
    assert parse_qr_decode(out, code).status == status


@pytest.mark.parametrize(
    "code,status",
    [
        (code, status)
        for code in QR_EXIT_STATUS
        for status in QR_EXIT_STATUS.values()
        if QR_EXIT_STATUS[code] != status
    ],
)
def test_an_exit_code_that_disagrees_with_the_status_is_refused(code, status):
    """The defect class this demo was built to close.

    A frame nobody could read must never arrive as a frame with nothing
    in it. The decoder states its outcome twice precisely so that it can
    be checked, and the one thing a reader must not do with the
    redundancy is pick a winner: if they disagree, neither is evidence.
    """
    out = decoded() if status == QR_DECODED else without_a_symbol(status)
    with pytest.raises(ValueError, match="independently sufficient"):
        parse_qr_decode(out, code)


def test_the_no_outcome_exit_code_is_not_parsed_as_any_outcome():
    # And the message must not volunteer a cause: being called wrongly is
    # one route to this code and not the only one, so naming it would send
    # the reader somewhere the exit code cannot say they should go.
    with pytest.raises(ValueError, match="no outcome it could report"):
        parse_qr_decode(without_a_symbol(QR_NO_QR), QR_EXIT_NO_OUTCOME)


def test_the_no_outcome_message_does_not_claim_the_caller_was_at_fault():
    try:
        parse_qr_decode(without_a_symbol(QR_NO_QR), QR_EXIT_NO_OUTCOME)
    except ValueError as e:
        assert "wrong arguments" not in str(e)
        assert "usage" not in str(e)
        assert "stderr" in str(e)


def test_an_undocumented_exit_code_is_refused_rather_than_mapped_to_the_nearest_one():
    with pytest.raises(ValueError, match="not one of its documented codes"):
        parse_qr_decode(decoded(), 139)


def test_a_payload_that_arrives_short_of_its_declared_length_is_refused():
    """Truncation is why the length is reported at all.

    Without this the short payload would be compared against the
    expectation, mismatch, and the run would report that the display
    showed the wrong thing — blaming the panel for a transport fault.
    """
    out = decoded().replace(
        f"QR_DECODE_PAYLOAD {NONCE.decode()}",
        f"QR_DECODE_PAYLOAD {NONCE.decode()[:-4]}",
    )
    with pytest.raises(ValueError, match="against a declared length"):
        parse_qr_decode(out, 0)


def test_a_payload_longer_than_its_declared_length_is_refused():
    # The decoder's payload buffer is fixed-size and not terminated past
    # the declared length, so a payload that runs long is the buffer
    # leaking rather than a longer symbol.
    out = decoded().replace(
        f"QR_DECODE_PAYLOAD_LEN {len(NONCE)}", f"QR_DECODE_PAYLOAD_LEN {len(NONCE) - 3}"
    )
    with pytest.raises(ValueError, match="against a declared length"):
        parse_qr_decode(out, 0)


def test_a_declared_length_is_not_read_as_a_payload():
    """The two records share a prefix and mean opposite things.

    A reader matching the shorter name first would take "20" as the
    payload and then find the real payload has no length, so the failure
    would arrive one record later and describe the wrong problem.
    """
    d = parse_qr_decode(decoded(), 0)
    assert d.codes[0].payload == NONCE
    assert d.codes[0].payload != str(len(NONCE)).encode()


def test_two_declared_lengths_with_no_payload_between_them_are_refused():
    out = (
        f"QR_DECODE_FILE {CAPTURE}\n"
        "QR_DECODE_COUNT 2\n"
        "QR_DECODE_PAYLOAD_LEN 4\n"
        "QR_DECODE_PAYLOAD_LEN 4\n"
        "QR_DECODE_PAYLOAD abcd\n"
        f"QR_DECODE_STATUS {QR_DECODED}\n"
    )
    with pytest.raises(ValueError, match="no payload between them"):
        parse_qr_decode(out, 0)


def test_a_payload_with_no_length_before_it_is_refused():
    out = (
        f"QR_DECODE_FILE {CAPTURE}\n"
        "QR_DECODE_COUNT 1\n"
        "QR_DECODE_PAYLOAD abcd\n"
        f"QR_DECODE_STATUS {QR_DECODED}\n"
    )
    with pytest.raises(ValueError, match="no length before it"):
        parse_qr_decode(out, 0)


def test_a_length_at_the_end_with_no_payload_is_refused():
    out = (
        f"QR_DECODE_FILE {CAPTURE}\n"
        "QR_DECODE_COUNT 1\n"
        f"QR_DECODE_STATUS {QR_DECODED}\n"
        "QR_DECODE_PAYLOAD_LEN 4\n"
    )
    with pytest.raises(ValueError):
        parse_qr_decode(out, 0)


def test_the_status_must_be_the_last_line_so_a_truncated_report_cannot_look_whole():
    # Diagnostics belong on stderr precisely so this cannot happen. A line
    # after the status means stdout carried something besides the report,
    # and then the status being present says nothing about it being whole.
    out = decoded() + "decoded 1 symbol in 41 ms\n"
    with pytest.raises(ValueError, match="not the last line"):
        parse_qr_decode(out, 0)


def test_a_report_with_no_status_is_refused_as_cut_short():
    out = "\n".join(decoded().splitlines()[:-1]) + "\n"
    with pytest.raises(ValueError, match="cut short"):
        parse_qr_decode(out, 0)


def test_a_count_that_disagrees_with_the_payloads_printed_is_refused():
    out = decoded().replace("QR_DECODE_COUNT 1", "QR_DECODE_COUNT 2")
    with pytest.raises(ValueError, match="printed"):
        parse_qr_decode(out, 0)


def test_a_decoded_status_with_nothing_decoded_is_refused():
    with pytest.raises(ValueError, match="both read and not read"):
        parse_qr_decode(without_a_symbol(QR_DECODED), 0)


def test_an_empty_outcome_carrying_a_symbol_is_refused():
    out = decoded().replace(
        f"QR_DECODE_STATUS {QR_DECODED}", f"QR_DECODE_STATUS {QR_NO_QR}"
    )
    with pytest.raises(ValueError, match="neither outcome has a symbol"):
        parse_qr_decode(out, 2)


def test_more_than_one_symbol_is_read_in_the_order_printed():
    out = (
        f"QR_DECODE_FILE {CAPTURE}\n"
        "QR_DECODE_COUNT 2\n"
        "QR_DECODE_PAYLOAD_LEN 3\n"
        "QR_DECODE_PAYLOAD one\n"
        "QR_DECODE_PAYLOAD_LEN 5\n"
        "QR_DECODE_PAYLOAD three\n"
        f"QR_DECODE_STATUS {QR_DECODED}\n"
    )
    assert [c.payload for c in parse_qr_decode(out, 0).codes] == [b"one", b"three"]


def test_an_unknown_record_is_refused_rather_than_skipped():
    """A record nobody here knows is a contract that moved.

    Skipping it is how a changed format goes unnoticed: the records this
    reader does know would still parse, and the report would look
    complete while meaning something else.
    """
    out = decoded().replace(
        "QR_DECODE_COUNT 1", "QR_DECODE_COUNT 1\nQR_DECODE_VERSION 2"
    )
    with pytest.raises(ValueError, match="unknown record"):
        parse_qr_decode(out, 0)


@pytest.mark.parametrize("record", ["QR_DECODE_FILE /other.jpg", "QR_DECODE_COUNT 1"])
def test_a_repeated_record_is_refused(record):
    out = decoded().replace("QR_DECODE_COUNT 1", f"QR_DECODE_COUNT 1\n{record}")
    with pytest.raises(ValueError, match="^two "):
        parse_qr_decode(out, 0)


def test_the_sudo_prompt_glued_to_the_first_record_does_not_hide_it():
    # Every record is recognised at the start of a line, and sudo's prompt
    # has no trailing newline, so the first record arrives glued to it.
    assert parse_qr_decode("Password: " + decoded(), 0).path == CAPTURE


def test_the_payload_comparison_is_what_catches_a_wrong_or_stale_frame():
    """The trap state: with the comparison removed, nothing else fails.

    This report is structurally perfect — a decoded symbol, agreeing
    count, agreeing exit code, status last. Every check in the parser
    passes. What it carries is the wrong payload, which is exactly what a
    photograph of the previous run's screen produces, and only comparing
    the bytes against this run's own payload can see it.
    """
    stale = parse_qr_decode(decoded(payload=b"edgelens-0000000previous"), 0)
    assert stale.decoded
    assert stale.codes[0].payload != NONCE
    assert parse_qr_decode(decoded(payload=NONCE), 0).codes[0].payload == NONCE


# ---- the records the decoder actually printed --------------------------------
#
# Everything above feeds the reader records this file builds itself. That
# shows what the reader does with a format; it cannot show that the format
# is the decoder's. Let the two drift and every test above keeps passing
# against a shape no device emits — the suite's own model of the decoder,
# never once compared against the decoder.
#
# So the records below are the decoder's own output, regenerated by running
# its suite rather than copied out of a report of it. A record pasted from a
# message goes stale the moment the binary changes and nothing about the
# paste would say so.
#
# One field is substituted and it is the only one. The decoder's suite reads
# files on a build host; the demo reads a frame off the device, so the path
# is the single field whose value here says nothing about the format. Every
# other byte is as printed, stderr and exit codes included.
#
# The two frames behind the empty-frame record are real 1920x1080
# photographs, 127728 and 185494 bytes, sha256 3ea84f9047b6105d3dd05f5b75ac
# 065c8ed05f9cf5c6d732bfc1df4d75c0e9cb and f178ce0395d023ffff39d55de0126041
# 93fedfeb68337d2afa1811040303ee34. One is a featureless colour gradient and
# one is a sharp picture of a face, and a run that judged a frame by how
# much detail it carried passed on both. They are named by digest because
# they are not tracked here and must not be: they are photographs off a
# rack and this is a published package.

REAL_PAYLOAD = b"EDGELENS-QR-FIXTURE-01HQZX8K4MP2T7VN"

REAL_DECODED = (
    "QR_DECODE_FILE /userdata/Models/capture.jpg\n"
    "QR_DECODE_COUNT 1\n"
    "QR_DECODE_PAYLOAD_LEN 36\n"
    "QR_DECODE_PAYLOAD EDGELENS-QR-FIXTURE-01HQZX8K4MP2T7VN\n"
    "QR_DECODE_STATUS DECODED\n"
)

# A frame the decoder read and found nothing in. Note what is absent rather
# than empty: no length line and no payload line at all.
REAL_NO_QR = (
    "QR_DECODE_FILE /userdata/Models/capture.jpg\n"
    "QR_DECODE_COUNT 0\n"
    "QR_DECODE_STATUS NO_QR\n"
)

REAL_FILE_ERROR = (
    "QR_DECODE_FILE /userdata/Models/capture.jpg\n"
    "QR_DECODE_COUNT 0\n"
    "QR_DECODE_STATUS FILE_ERROR\n"
)

# Measured, and the reason the run keeps stderr: the same QR photographed
# too small to resolve comes back as this, byte for byte. "There is a code
# here and it cannot be read" and "there is nothing on the panel" are the
# same record and the same exit code.
REAL_UNRESOLVED_QR = REAL_NO_QR

# Exit 1 prints nothing on stdout — not an empty record, not a partial one.
REAL_NO_OUTCOME_STDOUT = ""
REAL_NO_OUTCOME_STDERR = (
    "Usage: qr_decode <jpeg_file>",
    "qr_decode: the path contains a newline and cannot be reported",
)

# Only the outcomes with a cause to give put one on stderr.
REAL_NO_QR_STDERR = ""
REAL_FILE_ERROR_STDERR = (
    "qr_decode: cannot open /userdata/Models/capture.jpg",
    "qr_decode: cannot read an image from /userdata/Models/capture.jpg: "
    "Not a JPEG file: starts with 0x74 0x68",
)


def test_the_records_this_file_builds_are_the_ones_the_decoder_prints():
    """The drift check, and the reason this section exists.

    These three comparisons are the only place the suite's two record
    builders meet the decoder's real output. If the decoder's format
    moves, this is what fails — instead of nothing failing while every
    test above goes on proving things about a shape no device produces.
    """
    assert decoded(payload=REAL_PAYLOAD) == REAL_DECODED
    assert without_a_symbol(QR_NO_QR) == REAL_NO_QR
    assert without_a_symbol(QR_FILE_ERROR) == REAL_FILE_ERROR


@pytest.mark.parametrize("line", REAL_DECODED.strip().split("\n"))
def test_the_drift_check_is_sensitive_to_every_line_of_the_record(line):
    """The control: the comparison above must be able to fail.

    A comparison that held with a line missing would be agreeing about
    less of the format than it appears to, which is how a drift check
    becomes a check that cannot fail.
    """
    assert decoded(payload=REAL_PAYLOAD) != REAL_DECODED.replace(line + "\n", "")


def test_the_substituted_path_is_the_one_the_demo_actually_reads():
    """The one field above that is not the decoder's own output.

    Keeping it pinned separately means a change to the demo's capture
    path fails here, saying so, rather than failing the drift check and
    reading as a format change.
    """
    for record in (REAL_DECODED, REAL_NO_QR, REAL_FILE_ERROR):
        assert record.splitlines()[0] == f"QR_DECODE_FILE {CAPTURE}"


def test_a_frame_with_nothing_in_it_carries_neither_a_length_nor_a_payload():
    """Measured, and stricter than the contract's own wording.

    The contract says the payload line is omitted when the count is zero
    and says nothing about the length line. The decoder omits that too,
    so a reader written to the contract alone could require a length and
    reject a healthy report of an empty frame.
    """
    keywords = [line.partition(" ")[0] for line in REAL_NO_QR.splitlines()]
    assert keywords == ["QR_DECODE_FILE", "QR_DECODE_COUNT", "QR_DECODE_STATUS"]
    assert "QR_DECODE_PAYLOAD" not in REAL_NO_QR


def test_a_file_that_could_not_be_read_still_reports_a_count():
    """The count is printed on every route, this one included.

    It was twice read out of the decoder's source to settle it; this
    settles it from the decoder's output, which is the thing a reader
    here actually depends on.
    """
    assert "QR_DECODE_COUNT 0\n" in REAL_FILE_ERROR
    assert parse_qr_decode(REAL_FILE_ERROR, 3).status == QR_FILE_ERROR


@pytest.mark.parametrize(
    "record,code,status",
    [
        (REAL_DECODED, 0, QR_DECODED),
        (REAL_NO_QR, 2, QR_NO_QR),
        (REAL_FILE_ERROR, 3, QR_FILE_ERROR),
    ],
)
def test_every_real_record_parses_to_the_outcome_it_was_printed_with(record, code, status):
    assert parse_qr_decode(record, code).status == status


def test_the_real_records_cover_every_status_and_every_exit_code():
    """A case quietly leaving this section is the thing to catch.

    Three outcomes, the three codes that carry one, and the fourth code
    that carries none: the whole contract, asserted as covered rather
    than assumed to be.
    """
    covered = {
        parse_qr_decode(REAL_DECODED, 0).status,
        parse_qr_decode(REAL_NO_QR, 2).status,
        parse_qr_decode(REAL_FILE_ERROR, 3).status,
    }
    assert covered == set(QR_STATUSES)
    with pytest.raises(ValueError, match="no outcome"):
        parse_qr_decode(REAL_NO_OUTCOME_STDOUT, QR_EXIT_NO_OUTCOME)


def test_the_decoded_payload_survives_the_decoder_byte_for_byte():
    d = parse_qr_decode(REAL_DECODED, 0)
    assert d.decoded
    assert [(c.payload_len, c.payload) for c in d.codes] == [
        (len(REAL_PAYLOAD), REAL_PAYLOAD)
    ]
    assert len(REAL_PAYLOAD) == 36


def test_the_no_outcome_exit_prints_no_record_and_claims_no_outcome():
    """Its artifact is the absence of a report, and both its messages.

    Neither message names an outcome, which is the property that keeps
    this code from being read as "nothing was found": one of its two
    routes is a local resource failure on a file the decoder did read.
    """
    assert REAL_NO_OUTCOME_STDOUT == ""
    for message in REAL_NO_OUTCOME_STDERR:
        assert not any(status in message for status in QR_STATUSES)
        assert QR_RECORD_PREFIX not in message


def test_an_unreadable_code_and_an_empty_panel_differ_only_on_stderr():
    """Why a run that captured only the records would be blind.

    The same QR photographed too small to resolve produces the empty
    frame's record exactly, so a misaimed or out-of-focus camera and a
    screen showing nothing arrive identical. Only the diagnostics
    separate them, and a frame with nothing in it has none.
    """
    assert REAL_UNRESOLVED_QR == REAL_NO_QR
    assert parse_qr_decode(REAL_UNRESOLVED_QR, 2).status == QR_NO_QR
    assert REAL_NO_QR_STDERR == ""
    for message in REAL_FILE_ERROR_STDERR:
        assert message.startswith("qr_decode: ")
        assert not any(status in message for status in QR_STATUSES)


# ---- the blank-frame gate judges the annotation, and says so ----------------
#
# Two refusals that must not be confused. One says the threshold does not
# apply to a frame this size, so nothing is known about the picture. The
# other says it does apply and the picture has nothing in it. Reporting
# the first as the second would call a frame nobody could judge a frame
# that was judged and found empty.
#
# The sizes below are measurements, not fixtures: this example carries no
# image-encoding dependency, so there is no way to generate a synthetic
# JPEG here to feed in. The function under test takes a byte count and a
# geometry, which is exactly what the run passes it, so these exercise
# the gate the run consults rather than a re-derivation of its
# arithmetic. Provenance for each number is in the test.

# The preserved 2026-10-04 capture: 1920x1080, sha256 3ea84f90…, which is
# 0.4928 bits/pixel — under the threshold, and at a size the threshold was
# never measured at. Both facts are true of it, and only one is relevant.
GRADIENT_BYTES, GRADIENT_SIZE = 127728, (1920, 1080)
# The tracked annotated reference in models/, from the same pipeline as a
# run's own annotated result: 640x640, 1.61 bits/pixel.
REFERENCE_BYTES, REFERENCE_SIZE = 82585, (640, 640)


def test_a_frame_at_the_anchor_size_with_detail_in_it_is_accepted():
    assert annotated_frame_refusal(REFERENCE_BYTES, *REFERENCE_SIZE) is None


def test_a_frame_of_another_size_is_refused_as_unjudgeable_not_as_blank():
    """The guard fires, and what it says is the point.

    This frame also happens to score below the threshold, so a gate that
    checked density first would call it blank — a verdict about the
    picture, from a number that cannot support one at this size. The
    refusal must be about the size.
    """
    reason = annotated_frame_refusal(GRADIENT_BYTES, *GRADIENT_SIZE)
    assert reason is not None
    assert "1920x1080" in reason
    assert "cannot judge this frame" in reason
    assert "Nothing is known to be wrong with the picture" in reason
    # And it must not be the other refusal. Matched on the verdict itself,
    # not on the word "blank": this message names the blank-frame
    # threshold in order to say that it does not apply, so the word is
    # present in both and cannot tell them apart.
    assert "the returned frame is blank" not in reason
    # The trap: this frame is genuinely under the threshold, so removing
    # the size check would produce the blank verdict instead of this one.
    assert bits_per_pixel(GRADIENT_BYTES, *GRADIENT_SIZE) < BLANK_BITS_PER_PIXEL


def test_a_near_uniform_frame_at_the_anchor_size_is_refused_as_blank():
    """The density gate fires where it is entitled to.

    20,000 bytes over 640x640 is 0.39 bits/pixel — the shape a flat field
    compresses to, and well under the threshold. At the anchor size the
    threshold does apply, so here the verdict about the picture is the
    right kind of answer.
    """
    reason = annotated_frame_refusal(20_000, *REFERENCE_SIZE)
    assert reason is not None
    assert "the returned frame is blank" in reason
    assert "0.391 bits/pixel" in reason
    # Not the size refusal: this frame is at the anchor size.
    assert "cannot judge this frame" not in reason


def test_the_two_refusals_are_reported_as_different_things():
    """Neither is a substitute for the other, and that is the control.

    If they were collapsed, the 1920x1080 frame above would come back
    reported as blank — a statement about its content — when the only
    true statement available is that this measure cannot judge it.
    """
    size_refusal = annotated_frame_refusal(GRADIENT_BYTES, *GRADIENT_SIZE)
    blank_refusal = annotated_frame_refusal(20_000, *REFERENCE_SIZE)
    assert size_refusal != blank_refusal
    assert "the returned frame is blank" in blank_refusal
    assert "the returned frame is blank" not in size_refusal
    assert "cannot judge this frame" in size_refusal
    assert "cannot judge this frame" not in blank_refusal


# ---- one run's files are its own ---------------------------------------------
#
# Why runs must not share a directory, and why nothing may ever be deleted
# to keep them apart, is stated once at `new_run_dir` in demo_inference.

# Every name derived from the constants the run itself writes, rather than
# retyped here. That does not detect a rename and should not: the two move
# together by construction. What it rules out is the one-sided drift —
# these tests going on planting and checking a filename the run stopped
# writing, and passing while they do it.
SENTINEL_DEVICE_PATH = "/userdata/Models/capture.f004.jpg"
SENTINEL = fetched_artifact_name(SENTINEL_DEVICE_PATH)
RUN_WRITES = (
    ARTIFACT_RECORDS_NAME,
    ARTIFACT_ACCOUNTING_NAME,
    ARTIFACT_RESULT_NAME,
    fetched_artifact_name("/userdata/Models/capture.f000.jpg"),
    SENTINEL,
)
# The sentinel stands in for a frame a run reports and does not bring back,
# so a previous run's copy survives at that name to be read as this run's.
SENTINEL_BYTES = b"an earlier run's frame, larger than this run's" * 3


def simulate_run(target: pathlib.Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for name in RUN_WRITES:
        (target / name).write_bytes(b"this run")


def test_each_run_writes_into_a_directory_of_its_own(tmp_path):
    first = new_run_dir(tmp_path, datetime(2026, 10, 11, 9, 0, 0, tzinfo=timezone.utc))
    second = new_run_dir(tmp_path, datetime(2026, 10, 11, 9, 0, 1, tzinfo=timezone.utc))
    assert first != second
    assert first.parent == second.parent == tmp_path
    assert first.is_dir() and second.is_dir()


def test_an_earlier_runs_frame_survives_a_later_run_byte_for_byte(tmp_path):
    """`f004` is a frame a run reports and does not fetch, so an earlier
    run's copy sits at that name. It has a valid size and a matching
    digest; nothing about the file says which run produced it.
    """
    planted = tmp_path / SENTINEL
    tmp_path.mkdir(parents=True, exist_ok=True)
    planted.write_bytes(SENTINEL_BYTES)

    run = new_run_dir(tmp_path, datetime(2026, 10, 11, 9, 0, 0, tzinfo=timezone.utc))
    simulate_run(run)

    # The planted frame is untouched, which is the property that matters.
    assert planted.read_bytes() == SENTINEL_BYTES
    # And nothing landed in the shared directory beside it. Asserting that
    # the run's own files exist, or that their paths differ from the
    # planted one, would say nothing: the first is true of files the test
    # has just written, and the second is true of any two paths in
    # different directories whatever the code does.
    assert sorted(p.name for p in tmp_path.iterdir()) == [SENTINEL, run.name]


def test_the_sentinel_check_fails_when_the_run_is_not_given_its_own_directory(tmp_path):
    """The hazard itself, so the test above is not checking an empty room.

    Note what this does and does not establish. `simulate_run` is a
    hand-written stand-in, so this shows that writing a run's filenames
    into a shared directory destroys what was there — the thing worth
    preventing. It says nothing about whether the demo writes where it
    should; that is the next test, which calls what the run itself calls.
    """
    planted = tmp_path / SENTINEL
    tmp_path.mkdir(parents=True, exist_ok=True)
    planted.write_bytes(SENTINEL_BYTES)

    simulate_run(tmp_path)  # a run's filenames written into the shared base

    assert planted.read_bytes() != SENTINEL_BYTES, (
        "writing into the shared base directory did not overwrite the "
        "planted frame, so this test is not exercising the hazard it "
        "exists to describe"
    )


def test_the_run_itself_writes_to_a_subdirectory_and_not_to_the_shared_one(
    tmp_path, monkeypatch
):
    """The one that covers the call site rather than the helper.

    Everything above exercises the naming helper. This calls what the
    demo calls, through the documented directory override, so that
    pointing the run back at the shared directory fails here instead of
    passing everything and being found on hardware.
    """
    monkeypatch.setenv("EDGELENS_DEMO_ARTIFACT_DIR", str(tmp_path))
    from test_demo_end_to_end import artifact_base, this_run_dir

    assert artifact_base() == tmp_path
    planted = tmp_path / SENTINEL
    planted.write_bytes(SENTINEL_BYTES)

    d = this_run_dir()

    assert d.parent == tmp_path
    assert d != tmp_path
    assert d.name.startswith(ARTIFACT_RUN_PREFIX)
    assert not any(d.iterdir())
    assert planted.read_bytes() == SENTINEL_BYTES


def test_two_runs_in_the_same_second_still_do_not_share_a_directory(tmp_path):
    # A scheme that merges on collision has not namespaced anything; it has
    # moved the same defect somewhere less likely and harder to notice.
    when = datetime(2026, 10, 11, 9, 0, 0, tzinfo=timezone.utc)
    first = new_run_dir(tmp_path, when)
    second = new_run_dir(tmp_path, when)
    third = new_run_dir(tmp_path, when)
    assert len({first, second, third}) == 3
    simulate_run(first)
    assert not any((second / name).exists() for name in RUN_WRITES)


def test_the_run_directory_sorts_in_the_order_the_runs_happened(tmp_path):
    # A reader looking for their own run wants the newest directory, so the
    # newest has to be the one that sorts last.
    names = [
        artifact_run_name(datetime(2026, 10, 11, 9, 0, 0, tzinfo=timezone.utc)),
        artifact_run_name(datetime(2026, 10, 11, 9, 0, 1, tzinfo=timezone.utc)),
        artifact_run_name(datetime(2026, 10, 12, 8, 0, 0, tzinfo=timezone.utc)),
        artifact_run_name(datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)),
    ]
    assert names == sorted(names)


def test_the_base_directory_is_created_when_it_does_not_exist_yet(tmp_path):
    base = tmp_path / "artifacts"
    assert not base.exists()
    run = new_run_dir(base, datetime(2026, 10, 11, 9, 0, 0, tzinfo=timezone.utc))
    assert run.is_dir() and run.parent == base


# The stage-1 loop, driven end to end against a device that answers every
# step. Everything above tests a helper; this calls what the demo calls,
# so an ordering that only the sequence can get wrong fails here instead
# of on hardware with the session already gone.


def _tiny_jpeg(width: int = 1920, height: int = 1080) -> bytes:
    """Enough of a JPEG for the dimensions reader, and nothing more."""
    return (
        b"\xff\xd8"
        + b"\xff\xc0\x00\x11\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03"
        + b"\x00" * 16
    )


class _StubResult:
    def __init__(self, stdout: str, exit_code: int = 0):
        self.stdout = stdout
        self.exit_code = exit_code
        self.success = exit_code == 0


class _StubSsh:
    password = "stub-session-password"


class _StubDisplay:
    def __init__(self):
        self.source = None

    def show(self, url):
        self.source = url

    def status(self):
        return {"ready": True, "state": "showing", "source": self.source}


class _RecordingDevice:
    """Answers each step of stage 1 and records the order it was asked.

    The decode answers without the diagnostics marker, which is what the
    output split refuses. That is not an arbitrary choice of failure: a
    decode that finds no candidate is the run most likely to produce an
    output the split cannot divide, and it is the run whose photograph is
    worth most.
    """

    def __init__(self, frame: bytes, settled: str):
        self.frame = frame
        self.settled = settled
        self.display = _StubDisplay()
        self.calls: list[str] = []

    def ssh(self):
        return _StubSsh()

    def deploy(self, model=None, files=None):
        self.calls.append("deploy")

    # A shell that echoed a line it could not parse would put the whole
    # command on stdout, and the command carries the password. Switched
    # on only by the test that exists for it, because the guarantee is
    # worth nothing if the stub is the thing keeping it.
    echo_password = False

    def _leak(self, text: str) -> str:
        if not self.echo_password:
            return text
        return f"sh: cannot parse: echo {_StubSsh.password} | sudo -S\n{text}"

    def exec(self, command: str, timeout=None):
        if DECODER_FILE in command:
            self.calls.append("decode")
            return _StubResult(self._leak("QR_DECODE_COUNT 0\n"))
        if "sha256sum" in command:
            self.calls.append("listing")
            digest = hashlib.sha256(self.frame).hexdigest()
            return _StubResult(
                f"SIZE {len(self.frame)} SHA256 {digest} PATH {self.settled}\n"
            )
        if "base64" in command:
            self.calls.append("fetch")
            return _StubResult(base64.b64encode(self.frame).decode() + "\n")
        if CAPTURE_FILE in command:
            self.calls.append("capture")
            return _StubResult(self._leak(GOOD_CAPTURE))
        self.calls.append("preflight")
        return _StubResult("EXIT 0\n")


def test_the_photograph_is_fetched_before_the_decode_can_fail(tmp_path, monkeypatch):
    """A decoder answer the split refuses must not cost the frame.

    The split raises when the diagnostics marker is absent, and three
    writes and an exec sit between it and the fetch if the fetch comes
    second. The session is released immediately afterwards, so a frame
    still on the device is a frame that never existed.
    """
    import test_demo_end_to_end as e2e

    monkeypatch.setattr(e2e, "_stage_one_failure", STAGE_ONE_NOT_RUN)
    frame = _tiny_jpeg()
    device = _RecordingDevice(frame, "/userdata/Models/capture.jpg")

    with pytest.raises(ValueError):
        e2e.test_the_displayed_code_is_read_back_out_of_the_photograph(
            device, tmp_path
        )

    kept = [p for p in tmp_path.iterdir() if p.suffix == ".jpg"]
    assert kept, (
        "the decode failed and no photograph was kept, so the run that "
        "most needs measuring is the one that cannot be"
    )
    assert kept[0].read_bytes() == frame
    assert device.calls.index("fetch") < device.calls.index("decode"), (
        f"the frame was fetched after the decoder ran: {device.calls}"
    )


def test_output_that_cannot_be_split_is_kept_under_its_own_name(
    tmp_path, monkeypatch
):
    """Neither stream, rather than one of them, is still a run's output.

    The split is right to refuse output it cannot divide, but refusing
    it used to mean keeping nothing — on the one run where what the
    decoder said is least understood.
    """
    import test_demo_end_to_end as e2e

    monkeypatch.setattr(e2e, "_stage_one_failure", STAGE_ONE_NOT_RUN)
    device = _RecordingDevice(_tiny_jpeg(), "/userdata/Models/capture.jpg")

    with pytest.raises(ValueError):
        e2e.test_the_displayed_code_is_read_back_out_of_the_photograph(
            device, tmp_path
        )

    kept = [p for p in tmp_path.iterdir() if p.name.endswith(ARTIFACT_QR_UNSPLIT_NAME)]
    assert kept, f"nothing kept: {sorted(p.name for p in tmp_path.iterdir())}"
    assert kept[0].read_text() == "QR_DECODE_COUNT 0\n"


def test_no_artifact_the_run_writes_carries_the_session_password(
    tmp_path, monkeypatch
):
    """The credential control, aimed at the value rather than the prompt.

    It has never been in an artifact, but for a reason outside this
    harness: ``sudo -S`` reads the password from stdin and does not echo
    it. That is a property of sudo, and a change to how privileged
    commands are built would not be caught by anything that relies on
    it. So the device here is made to echo the password the way a shell
    reporting an unparseable line would, and the run must still write
    nothing containing it.
    """
    import test_demo_end_to_end as e2e

    monkeypatch.setattr(e2e, "_stage_one_failure", STAGE_ONE_NOT_RUN)
    device = _RecordingDevice(_tiny_jpeg(), "/userdata/Models/capture.jpg")
    device.echo_password = True

    with pytest.raises(ValueError):
        e2e.test_the_displayed_code_is_read_back_out_of_the_photograph(
            device, tmp_path
        )

    written = [p for p in tmp_path.iterdir() if p.suffix != ".jpg"]
    assert written, "nothing was written, so this proves nothing"
    leaked = [
        p.name for p in written if _StubSsh.password in p.read_text(errors="replace")
    ]
    assert not leaked, f"the session password reached {leaked}"

    # The device really did hand it over: without this the assertion
    # above would pass on a run where nothing could have leaked.
    assert any(
        PASSWORD_REDACTED in p.read_text(errors="replace") for p in written
    ), "the password was never in the stream, so the check above was vacuous"


# The quiet zone, which is the property two device windows turned on and
# which nothing here measured. The synthetic images below are built
# rather than downloaded: a fixture fetched at test time is a network
# dependency. The one real image is committed instead, because a
# measurement of the code we intend to display has to be re-takeable
# from the repository.


def _png(rows: list[list[bool]]) -> bytes:
    """Encode a dark/light grid as an 8-bit greyscale PNG."""
    raw = b"".join(
        b"\x00" + bytes(0 if dark else 255 for dark in row) for row in rows
    )

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            len(body).to_bytes(4, "big")
            + kind
            + body
            + zlib.crc32(kind + body).to_bytes(4, "big")
        )

    ihdr = (
        len(rows[0]).to_bytes(4, "big")
        + len(rows).to_bytes(4, "big")
        + bytes([8, 0, 0, 0, 0])
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _code(modules: int = 29, scale: int = 10, margin: int = 4, **sides) -> bytes:
    """A QR-shaped image: three finder patterns and a quiet zone.

    Only the geometry the measurement reads is real — the finders, the
    symbol's extent and the margins. The data area is a token pattern,
    because nothing here decodes it.
    """
    left = sides.get("left", margin)
    right = sides.get("right", margin)
    top = sides.get("top", margin)
    bottom = sides.get("bottom", margin)

    grid = [[False] * (modules + left + right) for _ in range(modules + top + bottom)]

    def finder(mx: int, my: int) -> None:
        for dy in range(7):
            for dx in range(7):
                ring = dx in (0, 6) or dy in (0, 6)
                core = 2 <= dx <= 4 and 2 <= dy <= 4
                grid[my + dy][mx + dx] = ring or core

    finder(left, top)
    finder(left + modules - 7, top)
    finder(left, top + modules - 7)
    for i in range(8, modules - 8, 2):
        grid[top + i][left + i] = True

    return _png(
        [
            [cell for cell in row for _ in range(scale)]
            for row in grid
            for _ in range(scale)
        ]
    )


def test_a_code_with_a_proper_quiet_zone_measures_four_modules():
    z = measure(_code(margin=4))
    assert z.square
    assert z.modules == 29
    assert (z.left, z.right, z.top, z.bottom) == (4.0, 4.0, 4.0, 4.0)
    assert z.smallest == 4.0


def test_a_code_cropped_flush_measures_zero_and_not_four():
    """The positive control: the instrument must return a different
    number for a code with no margin, or a reading of four is a default
    rather than a measurement. Codes printed flush to the frame edge on
    all four sides do occur in practice."""
    z = measure(_code(margin=0))
    assert (z.left, z.right, z.top, z.bottom) == (0.0, 0.0, 0.0, 0.0)
    assert z.smallest == 0.0
    assert z.modules == 29


def test_each_side_is_reported_separately():
    """A code clipped on one edge is the case the windows produced, and
    an instrument reporting a single number would average it away."""
    z = measure(_code(left=2, right=6, top=0, bottom=4))
    assert (z.left, z.right, z.top, z.bottom) == (2.0, 6.0, 0.0, 4.0)
    assert z.smallest == 0.0
    assert not z.square


def test_the_module_size_is_derived_from_the_finder_not_assumed():
    """Doubling the scale must not change a margin stated in modules."""
    small = measure(_code(scale=4, margin=4))
    large = measure(_code(scale=20, margin=4))
    assert small.module_px == 4.0 and large.module_px == 20.0
    assert small.left == large.left == 4.0


def test_an_image_with_nothing_in_it_is_refused_rather_than_measured():
    with pytest.raises(ValueError):
        measure(_png([[False] * 20 for _ in range(20)]))


# The code we intend to display, measured rather than eye-estimated. The
# tests above prove the instrument on geometry it builds itself; this one
# turns it on the real file, which is the only reading that decides
# anything.
#
# It is generated with the encoder's own four-module quiet zone and
# committed as that raster, so the margin measured here is the margin
# the display is handed.
QR_FIXTURE = pathlib.Path(__file__).resolve().parent.parent / "fixtures"
FEASIBILITY_QR_FIXTURE = QR_FIXTURE / "edgelens-www-qr.png"

# Identity is the digest, not the filename. A file can be replaced under
# the same name and address, and no margin changes with it. Pinning it is
# what keeps the measurement below attached to a known input rather than
# to whatever was written last.
FEASIBILITY_QR_FIXTURE_SHA256 = (
    "ab4ae0a3e612019d28edadbea7615ec8cfe6f5c53221b2519aac148fca9d7912"
)

# Four light modules on every side is the symbol's own requirement, and
# the margin here is measured in the image. What reaches the decoder is
# the margin in the *photograph*, which is smaller: the panel and the
# camera's aim both take from it.
QUIET_ZONE_MODULES_REQUIRED = 4.0

# The margin is read off a raster, so both the span and the module size
# carry the rasteriser's rounding. Expressing the allowance in pixels
# rather than in modules keeps it tied to the instrument's resolution
# instead of being a number chosen to make a reading pass: a file
# carrying three modules misses this by thirty times the allowance.
QUIET_ZONE_RASTER_SLACK_PX = 2.0


def test_the_tracked_candidate_is_the_file_the_margin_was_measured_on():
    assert (
        hashlib.sha256(FEASIBILITY_QR_FIXTURE.read_bytes()).hexdigest()
        == FEASIBILITY_QR_FIXTURE_SHA256
    )


def test_the_tracked_candidate_carries_its_own_quiet_zone():
    z = measure(FEASIBILITY_QR_FIXTURE.read_bytes())
    print(
        f"\n{FEASIBILITY_QR_FIXTURE.name}: {z.width}x{z.height} "
        f"symbol {z.span_px}px ({z.span_px / z.width:.3f} of width) "
        f"module {z.module_px:.2f}px over {z.modules} modules\n"
        f"  margins in modules: left {z.left:.2f} right {z.right:.2f} "
        f"top {z.top:.2f} bottom {z.bottom:.2f}"
    )
    floor = QUIET_ZONE_MODULES_REQUIRED - QUIET_ZONE_RASTER_SLACK_PX / z.module_px
    assert z.square
    assert z.left >= floor
    assert z.right >= floor
    assert z.top >= floor
    assert z.bottom >= floor


def test_the_candidates_margin_is_the_generators_default_and_nothing_more():
    """Why no second candidate was worth screening.

    The margin is not a property of this file that another file might
    improve on: a four-module border is what every encoder emits unless
    its author changed it, so the symbol occupies M/(M+8) of the image
    whatever version it is. This file is a version-2 symbol, 25 modules
    across, written with the encoder's default border of four.

    It matters because four modules in the image is the *most* a
    selected code offers, and the camera's framing has been measured to
    take about 5% of the image height off one edge.
    """
    z = measure(FEASIBILITY_QR_FIXTURE.read_bytes())
    assert z.modules == 25
    assert abs(z.span_px / z.width - z.modules / (z.modules + 8)) < 0.01


def test_the_kept_output_never_carries_sudos_prompt():
    assert unsplit_artifact_text("Password: QR_DECODE_COUNT 0\n") == (
        "QR_DECODE_COUNT 0\n"
    )


def test_nothing_at_all_is_kept_as_a_note_rather_than_an_empty_file():
    """An empty file and an absent one look the same and are not."""
    assert unsplit_artifact_text("Password: ") == QR_UNSPLIT_EMPTY_NOTE
    assert unsplit_artifact_text("") == QR_UNSPLIT_EMPTY_NOTE


# The gate between the two stages, at its call site. The decision helper
# above is pinned by the three tests near the top of this file, and that
# is a different claim: those say what the helper answers, these say the
# second stage asks it, and asks it first. The gate itself only ever runs
# on rented hardware, so without the tests below nothing offline would
# notice it being removed — and what it prevents is a stage-2 green that
# stage 1 never earned the right to produce.


def test_the_gate_stops_the_second_stage_when_the_first_one_failed(monkeypatch):
    """The refusal has to happen here, not only be decidable.

    Everything the second stage reports is attributed to the detector,
    which is only true if the camera was shown to resolve what is on the
    display. When it was not, the gate is the single thing standing
    between a failed first stage and a number that reads like a result.
    """
    import test_demo_end_to_end as e2e

    monkeypatch.setattr(e2e, "_stage_one_failure", STAGE_ONE_NOT_RUN)
    with pytest.raises(pytest.skip.Exception) as skipped:
        e2e._require_stage_one()
    assert "attributed to the detector" in str(skipped.value)

    monkeypatch.setattr(
        e2e, "_stage_one_failure", f"{RED_FROM_DISPLAY_CHECK} — the display never settled"
    )
    with pytest.raises(pytest.skip.Exception) as skipped:
        e2e._require_stage_one()
    assert "the display never settled" in str(skipped.value), (
        "the skip must carry the first stage's own words; a bare skip "
        "cannot be told from a stage nobody wrote"
    )


def test_the_gate_is_transparent_once_the_first_stage_has_passed(monkeypatch):
    """A gate that refuses a clean run is a gate nobody keeps.

    The converse matters as much as the refusal: if this raised, the
    second stage could never run, and the pressure would be to delete the
    gate rather than to fix it.
    """
    import test_demo_end_to_end as e2e

    monkeypatch.setattr(e2e, "_stage_one_failure", None)
    assert e2e._require_stage_one() is None


def test_the_gate_is_consulted_before_the_second_stage_does_anything():
    """Order, which is the property that actually protects the result.

    A gate called after the deploy has already pushed the model and the
    display is already showing an image has let the run happen; all it
    can still do is decline to report it. The deploy is also the step
    that can fail on its own, and a failure there would be attributed to
    the second stage rather than skipped.

    Asserted against the parsed source rather than by running the test,
    because the test needs a rented device and the ordering does not.
    A check that the call merely appears somewhere in the body would pass
    on exactly the arrangement this exists to refuse.
    """
    import test_demo_end_to_end as e2e

    body = ast.parse(inspect.getsource(e2e.test_demo_face_detection)).body[0].body
    first = body[0]
    assert (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Call)
        and isinstance(first.value.func, ast.Name)
        and first.value.func.id == "_require_stage_one"
    ), (
        "the first thing the second stage does must be to ask the gate, "
        f"and it is {ast.dump(first)}"
    )
