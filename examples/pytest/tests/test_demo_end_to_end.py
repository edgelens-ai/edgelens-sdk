"""End-to-end demo: allocate a reCamaginedOS session, put an image on the
device's display, deploy a face detector, photograph the display with the
device's own camera, run inference on that frame, bring the annotated
image back, and release.

That loop is the whole product in one test: the platform shows something
on your device's screen, your camera sees it, and your model detects
against it.

Run against a live platform:

    EDGELENS_API_KEY=...  EDGELENS_BASE_URL=https://<your-api> \\
        pytest tests/test_demo_end_to_end.py -v --edgelens-os recamagined

The `device` fixture (from edgelens-pytest) creates the session, waits
for readiness, and releases it in teardown. The camera is untrusted
customer hardware, so both capture and inference run customer-provided
binaries over SSH (`device.exec`), not a platform inference API.

The camera does not take one frame. It takes a short burst in a single
run — one immediately, the rest at intervals the capture utility chooses
— and reports the frame number, the elapsed time and the encoded size of
each. That burst is there because a camera needs a moment after starting
before it is exposing correctly, and a frame grabbed before then is dark
whatever is in front of the lens. The sizes make that visible: a frame
with nothing in it compresses to a fraction of a frame with detail, so
the sizes rising across the burst is the camera coming up.

The last frame of the burst is the one inference runs on. A few of the
images are brought back — the first, the last, and the pair either side
of any sharp rise — and the rest stay on the device, because their
numbers are already in the report and the numbers are the measurement.
Each frame that is not brought back is listed with the reason, so a frame
left behind on purpose is never mistaken for one that went missing.

What this test does and does not assert: it asserts that the display
reported it was showing *the image this test asked for*, that a frame
was captured from the sensor during this session, that the burst is
internally consistent and that every frame it reported is accounted for,
that the annotated image came back intact, and that it is not blank. It
does **not** assert what the model found, and it does **not** judge the
captured frames for content — the blank-frame measure is anchored at one
frame size, and the captured frames are a different one, where a perfectly
good picture scores below the threshold. Judging them by it would report a
working camera as blank in the one measurement arranged to find out
whether it works. The detections and the per-frame sizes are reported as
information: asserting on them would be testing the picture, not the
service.

The blank check and that last sentence are not in tension, because they
are about different things. Whether the frame carries any detail at all
is a property of the image and is measurable: a flat field compresses to
almost nothing. Whether the right thing is *in* the frame is a judgement
about the world, and belongs to whoever looks at the saved image. So the
test refuses a picture of nothing, and says nothing about a picture of
something.

The test drives the display itself: that is what puts a subject in front
of the lens. Before capturing it checks both halves of the display's
reported state, because a photograph of the wrong screen would satisfy
every other check in this file:

* `state` must be `showing` — but a display showing *anything* reports
  that, including content left over from before this test ran, so the
  state alone is not evidence that the request was honoured.
* `source` must be the URL this test requested. That is what rules out a
  stale image and a request that arrived somewhere altered. The
  comparison is exact, which assumes the platform reports the URL back
  unaltered rather than in some normalised form. If this ever fails on a
  display that is visibly working, compare the two URLs in the failure
  message before suspecting the hardware: a difference in only the
  spelling is this assumption breaking, not a dead display.

Neither check can prove what is lit up on the panel; only a person
looking at the returned frame can. What they rule out is the case where
nothing was shown and every assertion still passed.

Each run writes its images and records into a directory of its own,
named for the moment the run started, and prints that path before
anything else. Why that matters, and why nothing is ever deleted to
achieve it, is at `new_run_dir` in `demo_inference.py`.
"""

from __future__ import annotations

import hashlib
import http.client
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest

from demo_inference import (
    ARTIFACT_QR_DIAGNOSTICS_NAME,
    ARTIFACT_QR_RECORDS_NAME,
    ARTIFACT_QR_UNSPLIT_NAME,
    BLANK_BITS_PER_PIXEL,
    DISPLAY_IMAGE_URL,
    FEASIBILITY_QR,
    FEASIBILITY_QR_CANDIDATES,
    FEASIBILITY_QR_MODULES,
    FEASIBILITY_QR_URL,
    QR_PX_PER_MODULE_MEASURED_FAILING,
    QR_PX_PER_MODULE_MEASURED_PASSING,
    RED_FROM_DISPLAYED_ARTIFACT,
    RedAttribution,
    STAGE_ONE_NOT_RUN,
    attribute_red,
    display_bytes_unverified_note,
    verify_displayed_bytes,
    parse_qr_decode,
    qr_decode_command,
    required_capture_span_px,
    frame_payload_refusal,
    split_qr_output,
    stage_two_skip_reason,
    unsplit_artifact_text,
    without_session_password,
    FETCH_CHUNK_BYTES,
    FETCH_IMAGE_BOUND,
    KNEE_BYTES_RATIO,
    RESULT_PATH,
    accounting_table,
    annotated_frame_refusal,
    bits_per_pixel,
    capture_command,
    capture_output_paths,
    decode_chunk,
    fetch_chunk_command,
    fetched_length_disagreements,
    inference_command,
    jpeg_dimensions,
    ARTIFACT_ACCOUNTING_NAME,
    ARTIFACT_RECORDS_NAME,
    ARTIFACT_RESULT_NAME,
    fetched_artifact_name,
    listing_command,
    new_run_dir,
    parse_absent,
    parse_absent_globs,
    parse_capture_report,
    parse_digests,
    parse_inference,
    parse_sizes,
    parse_stat,
    paths_not_cleared,
    payload_paths,
    plan_capture_fetch,
    preflight_command,
    size_disagreements,
    unmeasured_paths,
)


# The gate between the two stages. It starts closed, and only the first
# stage's own verdict opens it.
#
# Closed-by-default is the whole mechanism. The failures most likely in a
# live run — a loader that cannot find a library, a rate limit, a capture
# that never arrives — end the first stage before it judges anything, and
# every one of them must stop the second stage just as a wrong payload
# would. "The first stage ran" is not "the first stage passed", and a gate
# keyed on execution would let exactly the likeliest failures through.
#
# It lives here rather than in the order the tests happen to be written,
# so moving a function cannot change what runs. Should the second stage be
# collected first, it finds the gate shut and skips, which is the safe
# direction.
_stage_one_failure: str | None = STAGE_ONE_NOT_RUN


def _write_artifact(path: Path, text: str, password: str) -> None:
    """Write device-derived text, with the session password taken out.

    Every artifact the run keeps goes through here rather than through
    ``write_text`` directly, so the guarantee is a property of the one
    way out and not of each caller remembering.
    """
    path.write_text(without_session_password(text, password))


def _keep_capture(device, password: str, path: str, artifacts: Path, label: str):
    """Bring one captured frame back and keep it, whatever the outcome.

    The device is wiped when the session ends, so a frame left on it is
    gone the moment the run finishes. That matters most for a run that
    failed: the question a failed decode raises is how large the code was
    in the photograph, and nothing but the photograph can answer it.

    Reported rather than asserted. A frame that will not come back is bad
    luck with a transfer, not a finding about the picture, and failing
    here would replace an answerable question with a different one.
    """
    try:
        ls = device.exec(listing_command(password, [path], [path]), timeout=120)
        size, sha = parse_digests(ls.stdout)[path]
        data = _fetch_file(device, password, path, size)
        out = artifacts / f"{label}-{fetched_artifact_name(path)}"
        out.write_bytes(data)
        intact = hashlib.sha256(data).hexdigest() == sha
        width, height = jpeg_dimensions(data)
        print(
            f"[demo] {label}: kept {out} — {size} bytes, {width}x{height}, "
            f"digest {'matches' if intact else 'DIFFERS FROM'} the device's"
        )
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        print(
            f"[demo] {label}: the capture could not be brought back "
            f"({type(exc).__name__}: {exc}). The decode result stands; what "
            f"is lost is the ability to measure the code's size in the frame."
        )


def _require_stage_one() -> None:
    reason = stage_two_skip_reason(_stage_one_failure)
    if reason is not None:
        pytest.skip(reason)


def artifact_base() -> Path:
    """The directory each run's own subdirectory is created under.

    Gitignored: the images are photographs of whatever the rented device
    can see, and this repository is published.
    """
    d = os.environ.get("EDGELENS_DEMO_ARTIFACT_DIR")
    return Path(d) if d else Path(__file__).resolve().parent.parent / "artifacts"


def this_run_dir() -> Path:
    """This run's own directory, which no other run writes to.

    The fixture below is a thin wrapper around this so that what the run
    actually uses is reachable without a device. A test that exercises
    only the directory-naming helper proves the helper works and nothing
    about whether the run calls it.
    """
    return new_run_dir(artifact_base(), datetime.now(timezone.utc))


@pytest.fixture
def artifacts() -> Path:
    """One directory per test, printed as the first thing the run says.

    Printed because the only way to be sure which files are yours is to
    be told, and a reader who has to work out the naming scheme to find
    their own images is one bad guess away from reading someone else's.

    Per test, not per session, and the docstring says so because the
    difference is visible: there is one test here today, and if a second
    device test is added it gets a directory of its own rather than
    writing its files in beside this one's. That is the fail-closed
    direction — two tests can no more collide than two runs can — and it
    needs no knowledge of how the session fixture is scoped, which a
    session-scoped version of this would.
    """
    d = this_run_dir()
    print(f"[demo] this run writes to {d}")
    return d


def _fetch_file(device, password: str, path: str, size: int) -> bytes:
    """Pull a file back through `exec` stdout, in ranges.

    There is no download API on the platform, and `exec` stdout is capped
    at 256 KiB. base64 inflates 4/3, so anything bigger than a fraction
    of that has to come back in pieces.

    The per-chunk length check and the whole-file digest comparison in the
    caller are what actually guarantee the image is intact; the truncation
    marker `decode_chunk` looks for is only a faster, clearer failure.
    """
    chunks: list[bytes] = []
    offset = 0
    while offset < size:
        length = min(FETCH_CHUNK_BYTES, size - offset)
        r = device.exec(
            fetch_chunk_command(password, path, offset, length), timeout=120
        )
        assert r.success, f"fetch at offset {offset} exited {r.exit_code}:\n{r.stdout}"
        chunk = decode_chunk(r.stdout)
        assert len(chunk) == length, (
            f"fetch at offset {offset} returned {len(chunk)} bytes, expected {length}"
        )
        chunks.append(chunk)
        offset += length
    return b"".join(chunks)


# Long enough that a slow host is not read as a dead one, short enough
# that a dead one does not eat the window it is protecting.
DISPLAY_FETCH_TIMEOUT_S = 20


def _fetch_served_bytes(url: str) -> bytes:
    """Whatever the address serves right now.

    The only line in this example that reaches the network from the
    harness, and it is reached only from the demo target, which is the
    one that has a network. The offline suite runs with the network
    denied and hands bytes to the verification directly, so nothing here
    may be called at import or collection time.

    ``urllib`` rather than a client library because an example that
    needs a package installed to check its own input has moved the cost
    onto every customer who copies it.
    """
    request = urllib.request.Request(
        url, headers={"User-Agent": "edgelens-sdk-demo/1.0"}
    )
    with urllib.request.urlopen(request, timeout=DISPLAY_FETCH_TIMEOUT_S) as response:
        return response.read()


def _refuse_an_unmeasured_code() -> None:
    """Stop before the window is spent on a code nobody measured.

    The device fetches the display source itself, so the bytes it
    photographs never pass through this harness and nothing had ever
    hashed them. The offline suite hashes the committed copy, which is a
    different artifact at the same address: it cannot see a re-render.
    So the harness fetches the same address once, here, before anything
    is deployed or displayed.

    A fetch that fails is not a mismatch. This network is not the
    device's, and ending the run on a transient error would turn a blip
    into a lost window — worse than the bug being fixed. It is reported,
    the margin is declared unverified for this run, and the run goes on.
    Only bytes that arrived and disagree are a stop.
    """
    try:
        served = _fetch_served_bytes(FEASIBILITY_QR.url)
    except (OSError, http.client.HTTPException) as error:
        note = display_bytes_unverified_note(
            FEASIBILITY_QR, f"{type(error).__name__}: {error}"
        )
        print(f"\n[demo] {note}")
        return

    check = verify_displayed_bytes(served, FEASIBILITY_QR)
    if check.mismatch_reason is not None:
        refusal = RedAttribution(RED_FROM_DISPLAYED_ARTIFACT, check.mismatch_reason)
        pytest.fail(f"{refusal.source} — {refusal.reason}")
    print(
        f"\n[demo] the address still serves the measured artifact: sha256 "
        f"{check.actual_sha256} over {check.size_bytes} bytes"
    )


@pytest.mark.edgelens(os="recamagined", device_type="recamera-2002")
def test_the_displayed_code_is_read_back_out_of_the_photograph(device, artifacts):
    """Show a known code, photograph it, read it back, compare the bytes.

    This is the whole loop with the judgement taken out of it. The other
    test in this file photographs a face and reports what a model made of
    it; nobody can say from its output whether the camera resolved the
    screen or merely pointed at something bright. A payload either comes
    back or it does not, and it only comes back if the display rendered
    it, held it, and the camera resolved it well enough to read.

    The code is selected rather than generated here, which is deliberate
    and is what this particular run is for: it answers whether the
    optical path can carry a code at all, and selecting one keeps an
    encoder, somewhere to host it and an offline decoder off that
    question's critical path.

    Nothing here knows what the code says, and nothing should. Its
    payload is published nowhere trustworthy, so an expectation written
    into this file would be a guess — and a run that disagreed with a
    guess could not be told from a run that read the screen correctly.
    What stands in for the expectation is agreement between two
    photographs: the symbol carries its own error correction, so a
    decoder does not return bytes it has not checked against the
    symbol's own codewords, and two reads that agree have established
    what was on the screen without anyone knowing it in advance.

    What a red here does and does not mean is decided by the run rather
    than by whoever reads it afterwards: see the attribution at the end.
    A code too small or too blurred to resolve and a display with nothing
    on it produce the same status and the same exit code, and differ only
    on the decoder's stderr, which is why both streams are kept.
    """
    # First, because every margin figure this run is judged against is a
    # property of the bytes at that address and the address does not pin
    # them. Nothing is deployed or displayed until they agree.
    _refuse_an_unmeasured_code()

    bundled = payload_paths()
    password = device.ssh().password
    device.deploy(model=str(bundled.model), files=bundled.as_files())

    attribution = None
    decodes: list = []

    for index, url in enumerate(FEASIBILITY_QR_CANDIDATES):
        label = f"c{index}"
        print(f"\n[demo] {label}: displaying {url}")

        # Push twice if the first is not honoured: a display can reject the
        # first request after starting up and keep showing what it had.
        def shows(wanted: str = url) -> tuple[bool, dict]:
            s = device.display.status()
            return s.get("state") == "showing" and s.get("source") == wanted, s

        device.display.show(url)
        showing, status = shows()
        if not showing:
            device.display.show(url)
            showing, status = shows()
        print(f"[demo] {label}: display status: {status}")

        decode = None
        records = ""
        diagnostics = ""

        if showing:
            pre = device.exec(preflight_command(password), timeout=60)
            assert pre.success, f"preflight exited {pre.exit_code}:\n{pre.stdout}"

            cap = device.exec(capture_command(password), timeout=180)
            print(f"[demo] {label}: capture:\n{cap.stdout}")
            _write_artifact(
                artifacts / f"{label}-{ARTIFACT_RECORDS_NAME}",
                cap.stdout,
                password,
            )
            report = parse_capture_report(cap.stdout)
            assert cap.success, f"capture exited {cap.exit_code}:\n{cap.stdout}"
            assert report.settled_path is not None, (
                f"the capture reported {report.status} and named no settled "
                f"frame, so there is nothing for the decoder to read"
            )

            # The photograph, fetched the moment there is a path to fetch
            # and before the decoder is asked anything. A run that decodes
            # needs it least and a run that does not cannot be diagnosed
            # without it: how many pixels each module spans in this frame
            # is the quantity that decides the result, and it cannot be
            # recovered once the device is released. Everything between
            # here and the verdict can raise, and a raise leaves the frame
            # on a device that is about to be wiped.
            _keep_capture(device, password, report.settled_path, artifacts, label)

            run = device.exec(
                qr_decode_command(password, report.settled_path), timeout=120
            )
            try:
                records, diagnostics = split_qr_output(run.stdout)
            except ValueError:
                # The split refuses what it cannot divide, and it is right
                # to, but that leaves the run with neither file. Keep what
                # arrived under its own name, so it can never be read as
                # either of the two streams it could not be separated into.
                _write_artifact(
                    artifacts / f"{label}-{ARTIFACT_QR_UNSPLIT_NAME}",
                    unsplit_artifact_text(run.stdout),
                    password,
                )
                raise

            # Written before anything is asserted. The two streams are what
            # separate a code that was found and could not be read from one
            # that was never there, and that distinction exists nowhere
            # else: an empty diagnostics file is the signal, not a missing
            # measurement.
            _write_artifact(
                artifacts / f"{label}-{ARTIFACT_QR_RECORDS_NAME}", records, password
            )
            _write_artifact(
                artifacts / f"{label}-{ARTIFACT_QR_DIAGNOSTICS_NAME}",
                diagnostics,
                password,
            )
            print(f"[demo] {label}: decoder records:\n{records}")
            print(f"[demo] {label}: decoder diagnostics:\n{diagnostics or '(none)'}")

            decode = parse_qr_decode(records, run.exit_code)

        decodes.append(decode)
        attribution = attribute_red(showing, decode, None)
        print(f"[demo] {label}: attribution: {attribution.source} — {attribution.reason}")
        if decode is not None and decode.decoded and decode.codes:
            print(
                f"[demo] {label}: read {decode.codes[0].payload!r} "
                f"({decode.codes[0].payload_len} bytes)"
            )

    # Both photographs are taken before either is judged. Stopping at the
    # first success would leave one reading, and one reading cannot be
    # compared with anything — the whole point of the second is that it
    # replaces an expectation nobody is entitled to write down.
    agreement = frame_payload_refusal(decodes)

    # Recorded before the assertion, so the gate carries the reason rather
    # than the fact. Set here and nowhere else: anything that ends this
    # test earlier leaves the gate shut, which is what makes a loader
    # failure or a capture that never arrived stop the next stage too.
    global _stage_one_failure
    _stage_one_failure = (
        None if agreement is None else f"{attribution.source} — {agreement}"
    )

    assert agreement is None, (
        f"two photographs of the displayed code did not establish one "
        f"payload between them. {agreement}\n"
        f"The last capture is attributable to {attribution.source}: "
        f"{attribution.reason}\n"
        f"Every capture was kept beside this run's records — measure how "
        f"many pixels each module spans in them before concluding anything "
        f"about the optical path. At {FEASIBILITY_QR_MODULES} modules, "
        f"{required_capture_span_px(FEASIBILITY_QR_MODULES, QR_PX_PER_MODULE_MEASURED_PASSING)} px "
        f"across is the density that has decoded and "
        f"{required_capture_span_px(FEASIBILITY_QR_MODULES, QR_PX_PER_MODULE_MEASURED_FAILING)} px "
        f"is the one that has not."
    )


@pytest.mark.edgelens(os="recamagined", device_type="recamera-2002")
def test_demo_face_detection(device, artifacts):
    # Nothing measured below can be attributed to the detector unless the
    # stage above established that the camera resolves what is on the
    # display. Checked first, before anything is deployed or shown.
    _require_stage_one()

    payload = payload_paths()
    password = device.ssh().password

    # 1. Push the model, the capture utility, the inference binary and the
    #    sample image to the camera. They land in /userdata/Models/.
    device.deploy(model=str(payload.model), files=payload.as_files())

    # 2. Put an image on the device's display, so the camera has a subject.
    #    The device fetches the URL itself, so it must be publicly reachable.
    print(f"[demo] display status before show: {device.display.status()}")
    device.display.show(DISPLAY_IMAGE_URL)
    status = device.display.status()
    print(f"[demo] display status after show: {status}")

    # A display can reject the first request it receives after starting up,
    # and when it does it keeps showing whatever it had. Confirm it reports
    # our image, and ask once more if it does not — `show()` has no return
    # value to tell you either way.
    def showing_requested_image(s: dict) -> bool:
        return s.get("state") == "showing" and s.get("source") == DISPLAY_IMAGE_URL

    reissued = False
    if not showing_requested_image(status):
        device.display.show(DISPLAY_IMAGE_URL)
        reissued = True
        status = device.display.status()
        print(f"[demo] display status after second show: {status}")

    assert status.get("state") == "showing", (
        f"display never reported showing, so there is nothing to photograph: {status}"
    )

    # `state` is satisfied by any content at all, so it does not distinguish
    # our image from what was on screen beforehand. The reported source is
    # what does, and it is also where a URL that was altered in transit
    # shows up: the device fetches this URL itself, so a source that is not
    # the one requested is a different fetch than the one under test.
    assert status.get("source") == DISPLAY_IMAGE_URL, (
        f"display reports source {status.get('source')!r}, not the requested "
        f"{DISPLAY_IMAGE_URL!r} — the camera would photograph the wrong "
        f"subject: {status}"
    )

    # 3. Prove every path a capture run writes is empty beforehand. The
    #    capture utility opens each output file only once a frame arrives,
    #    so a failed run leaves an earlier run's images in place and the
    #    exit code does not say so. Absence beforehand is what makes
    #    presence afterwards evidence.
    #
    #    The burst is cleared by pattern because its length is the capture
    #    utility's decision. Clearing only the settled frame's own name
    #    would leave a whole previous burst behind, and those files pass
    #    every later check: they are real images whose sizes and digests
    #    agree. They are simply from a different run.
    pre = device.exec(preflight_command(password), timeout=60)
    print(f"[demo] preflight:\n{pre.stdout}")
    assert pre.success, f"preflight exited {pre.exit_code}:\n{pre.stdout}"
    absent = parse_absent(pre.stdout)
    absent_globs = parse_absent_globs(pre.stdout)
    exact_paths, series_glob = capture_output_paths()
    for path in exact_paths:
        assert path in absent, f"{path} still present after rm:\n{pre.stdout}"
    assert series_glob in absent_globs, (
        f"the burst pattern {series_glob} was not proved empty, so any frame "
        f"this run reports could be left over from an earlier one:\n{pre.stdout}"
    )

    # 4. Capture a burst of frames. One run, because starting the sensor
    #    again restarts whatever it does on startup — separate runs would
    #    each measure the same first frame instead of a progression.
    cap = device.exec(capture_command(password), timeout=180)
    print(f"[demo] capture:\n{cap.stdout}")

    # Save what the run reported before anything is checked. For the frames
    # that are never brought back, these records are the only trace that
    # will survive the device being wiped, and they are the measurement
    # this run exists to produce.
    records = artifacts / ARTIFACT_RECORDS_NAME
    _write_artifact(records, cap.stdout, password)

    report = parse_capture_report(cap.stdout)
    print(
        f"[demo] capture schedule: n={len(report.schedule)} "
        f"indices={','.join(str(i) for i in report.schedule)}"
    )
    for f in report.in_order():
        print(
            f"[demo] frame {f.frame}: {f.elapsed_ms} ms, {f.size_bytes} bytes "
            f"-> {f.path}"
        )

    # A frame at a path the preflight never cleared could be left over from
    # an earlier run, and nothing about the file itself would say so.
    uncleared = paths_not_cleared(report, absent, absent_globs)
    assert not uncleared, (
        f"the run reports frames at paths the preflight never proved gone: "
        f"{', '.join(uncleared)}. Those files may be from an earlier run — "
        f"they would have a valid size and a matching digest either way."
    )

    # 4a. Decide which images come back, and account for the rest. Every
    #     reported frame is either fetched or listed with the reason it was
    #     not, because a frame deliberately left on the device and a frame
    #     quietly forgotten look identical once the device is released.
    plan = plan_capture_fetch(report)
    assert plan.accounts_for(report), (
        "the fetch plan does not account for every reported frame: "
        f"fetching {plan.fetch}, skipping {[p for p, _ in plan.skipped]}, "
        f"reported {[f.path for f in report.frames]}"
    )
    assert len(plan.fetch) <= FETCH_IMAGE_BOUND, (
        f"the plan would fetch {len(plan.fetch)} images against a bound of "
        f"{FETCH_IMAGE_BOUND}"
    )
    for path, reason in plan.skipped:
        print(f"[demo] not fetched: {path} — {reason}")

    # The account goes to a file, not only to this output. The frames that
    # stay behind are described by nothing else once the device is wiped,
    # and a decision that lives only in a test's stdout is one scrollback
    # from being taken again on hardware.
    accounting = artifacts / ARTIFACT_ACCOUNTING_NAME
    accounting.write_text(accounting_table(report, plan))

    # 4b. One listing: measure every reported path, hash the ones coming
    #     back. The hash set is already known, so there is nothing to wait
    #     for and no reason for a second round trip.
    claimed = [f.path for f in report.frames]
    if report.settled_path is not None and report.settled_path not in claimed:
        claimed.append(report.settled_path)

    on_disk: dict[str, int] = {}
    device_digests: dict[str, tuple[int, str]] = {}
    if claimed:
        ls = device.exec(
            listing_command(password, claimed, list(plan.fetch)), timeout=120
        )
        assert ls.success, f"listing exited {ls.exit_code}:\n{ls.stdout}"
        on_disk = parse_sizes(ls.stdout)
        if plan.fetch:
            device_digests = parse_digests(ls.stdout)

        # The comparison below can only disagree about a path it has a
        # size for, so without this it would be satisfied by a listing
        # that measured almost nothing — fewer measurements, fewer
        # disagreements. Checking coverage first gives it a denominator.
        unmeasured = unmeasured_paths(claimed, on_disk)
        assert not unmeasured, (
            "the listing returned no size for "
            f"{', '.join(unmeasured)}, so the check for a write that "
            "stopped early cannot run on those frames at all"
        )

        # What the camera says it wrote, against what is actually there.
        # For a frame that never comes back this is the only check that
        # can see a write which stopped early.
        short = size_disagreements(report, on_disk)
        assert not short, (
            "the run's own byte count disagrees with the files on the device, "
            "so a write stopped early: "
            + "; ".join(
                f"{p} reports {reported} bytes, measured {measured}"
                for p, reported, measured in short
            )
        )

    saved: dict[str, Path] = {}
    received: dict[str, int] = {}
    if plan.fetch:
        for path in plan.fetch:
            size, sha = device_digests[path]
            data = _fetch_file(device, password, path, size)
            received[path] = len(data)
            assert hashlib.sha256(data).hexdigest() == sha, (
                f"{path} digest after transfer does not match the device's {sha}"
            )
            out = artifacts / fetched_artifact_name(path)
            out.write_bytes(data)
            saved[path] = out
            width, height = jpeg_dimensions(data)
            # Reported, never asserted. The blank-frame threshold is
            # anchored at one frame size and these frames are a different
            # one, where a good picture scores below it — gating on that
            # here would report a working camera as blank in the one
            # experiment meant to settle whether it works.
            print(
                f"[demo] fetched {path} -> {out} — {size} bytes, "
                f"{width}x{height}, {bits_per_pixel(size, width, height):.3f} "
                f"bits/pixel (observation only)"
            )

        # The third of the three counts, and it is the camera's own account
        # against the bytes that arrived. The digest above compares the
        # arrival with the listing; both of those are measurements of the
        # file as it now exists. Only this one involves what the camera
        # said it wrote.
        arrived = fetched_length_disagreements(report, received)
        assert not arrived, (
            "the run's own byte count disagrees with what came back: "
            + "; ".join(
                f"{p} reports {reported} bytes, received {got}"
                for p, reported, got in arrived
            )
        )

    if plan.knee_frame is not None:
        print(
            f"[demo] encoded detail rises sharply by frame {plan.knee_frame} "
            f"(more than {KNEE_BYTES_RATIO}x the first frame)"
        )
    elif report.frames:
        # Not an assertion, for the same reason as above — but it must not
        # read as an ordinary result either. A burst whose frames all carry
        # the same little detail as the first one is the finding this run
        # was arranged to look for.
        print(
            f"[demo] FINDING: the encoded size never rose above "
            f"{KNEE_BYTES_RATIO}x the first frame across all "
            f"{len(report.frames)} frames, so nothing in the burst carries "
            f"more detail than the frame taken immediately. Compare the first "
            f"and settled images by eye before concluding anything about the "
            f"subject."
        )

    # Only now may the run be failed. The capture utility keeps its frames
    # and its records on a failed run on purpose, so failing before they are
    # fetched would throw away the evidence at the one moment it is the only
    # evidence there is — the device is released at the end of this test.
    assert report.complete, (
        f"capture reported {report.status} with {len(report.frames)} of "
        f"{len(report.schedule)} scheduled frames. Records saved at {records}; "
        f"images saved: {', '.join(str(p) for p in saved.values()) or 'none'}."
    )
    assert cap.success, f"capture exited {cap.exit_code}:\n{cap.stdout}"
    assert report.settled_path is not None
    cap_size = report.frame_at(report.settled_frame).size_bytes
    print(
        f"[demo] settled frame is {report.settled_frame}, "
        f"{cap_size} bytes, at {report.settled_path}"
    )

    # 5. Run the face detector over the settled frame.
    inf = device.exec(inference_command(password), timeout=120)
    print(f"[demo] inference:\n{inf.stdout}")
    assert inf.success, f"inference exited {inf.exit_code}:\n{inf.stdout}"
    result_size, result_sha = parse_stat(inf.stdout)
    assert result_size > 0, "inference wrote a zero-length annotated frame"

    # 6. Bring the annotated frame back and verify it survived the trip.
    data = _fetch_file(device, password, RESULT_PATH, result_size)
    local_sha = hashlib.sha256(data).hexdigest()
    assert local_sha == result_sha, (
        f"fetched image digest {local_sha} != device digest {result_sha}"
    )
    width, height = jpeg_dimensions(data)
    out = artifacts / ARTIFACT_RESULT_NAME
    out.write_bytes(data)

    # Is there a picture of anything here? A frame of an unlit screen satisfies
    # every check above — it is a real file, from this run, with a matching
    # digest — and it is worthless. Measure whether the frame carries enough
    # information to be a photograph before anyone is asked to look at it.
    #
    # This says nothing about what is IN the frame. It does not count faces, it
    # does not read the detections, and it is not a threshold on the model's
    # output: what the picture shows is for the person looking at it to judge.
    # This only refuses to waste their time on a blank one.
    #
    # The geometry is checked before the density, and a frame of the wrong
    # size is refused as unjudgeable rather than as empty — otherwise a good
    # picture at a larger size scores low and gets called blank, which is a
    # wrong answer dressed as a verdict about the content. Both refusals
    # come from one place so that a test can reach them.
    refusal = annotated_frame_refusal(len(data), width, height)
    assert refusal is None, f"{refusal} Saved at {out}."

    density = bits_per_pixel(len(data), width, height)
    # Name the image. This number is the density of the ANNOTATED result at
    # its own size, and the run prints another density earlier for each
    # captured frame. An unlabelled figure here was read as a statement
    # about the photograph, which it has never been: the annotation
    # inherits detail from the boxes and text drawn onto it, so it scores
    # higher than the frame underneath and says nothing about the scene.
    print(
        f"[demo] information density of the annotated result "
        f"({width}x{height}): {density:.3f} bits/pixel "
        f"(blank below {BLANK_BITS_PER_PIXEL}; this is not a measurement "
        f"of the captured frame)"
    )
    # 7. Report what the run saw. Information, not a pass condition.
    inference = parse_inference(inf.stdout)
    candidates = inference.candidates

    # Boxes that are not rectangles are reported, not dropped. A detector
    # emitting one is telling you something went wrong, and a filter that
    # hid them would be the last anyone saw of it — which is as true of
    # your own model as of the one bundled here.
    for box, reason in inference.rejected:
        print(
            f"[demo] not a candidate: x={box.x:.6f} y={box.y:.6f} "
            f"w={box.w:.6f} h={box.h:.6f} score={box.score:.6f} — {reason}"
        )

    print(
        f"[demo] sensor capture: frame {report.settled_frame} of "
        f"{len(report.schedule)} scheduled, {cap_size} bytes\n"
        f"[demo] capture records: {records}\n"
        f"[demo] frame-by-frame account: {accounting}\n"
        f"[demo] images brought back: "
        + (", ".join(str(p) for p in saved.values()) or "none")
        + f"\n[demo] annotated frame: {out} — {result_size} bytes, "
        f"{width}x{height}, sha256 {result_sha}\n"
        f"[demo] detections: {len(candidates)} candidate(s) from "
        f"{len(inference.detections)} emitted"
        + (
            f", top score {max(d.score for d in candidates):.3f}"
            if candidates
            else " (none — the scene may have no faces in it)"
        )
        + f"\n[demo] displayed: {DISPLAY_IMAGE_URL}"
        + f"\n[demo] display re-issue needed: {reissued}"
        + f"\n[demo] final display status: {status}"
        + f"\n[demo] timing: pre {inference.pre_ms}ms, "
        f"infer {inference.infer_ms}ms, post {inference.post_ms}ms"
    )
