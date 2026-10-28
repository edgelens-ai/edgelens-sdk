"""Helpers for the end-to-end face-detection demo.

The reference payload under ``examples/pytest/models/`` is a standalone
RISC-V capture utility (``capture_jpeg``), an inference CLI
(``sscma-model``), an int8 SCRFD face model, and a sample image used by
the offline parser tests.

The demo captures a frame from the camera's own sensor, runs the model on
that frame, and brings the annotated result back. Both binaries need root
(the sensor and TPU character devices are ``0600 root:root``) and an
explicit library search path (the CV181X runtime libs aren't on the
default ``LD_LIBRARY_PATH``), so every command goes through ``sudo`` with
the per-session password.

This module has no SDK dependency so its parsing and command building can
be unit-tested without a live device.
"""

from __future__ import annotations

import base64
import fnmatch
import hashlib
import re
import secrets
import shlex
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# The image the platform puts on the device's display, so the camera has
# something to photograph. Public domain, fetched by the device itself, so
# it has to be reachable from wherever the device is.
DISPLAY_IMAGE_URL = (
    "https://upload.wikimedia.org/wikipedia/commons/d/d3/Albert_Einstein_Head.jpg"
)

# The code the frame displays, and the copy of it committed here.
#
# One record rather than separate constants, because the address, the
# committed bytes and everything measured from them have to stay the same
# artifact. The margin of white around the symbol is what decides whether
# it can be decoded at all, and a margin measured from one file while
# another is displayed measures nothing. Splitting them is how the two
# drifted apart once already: the chosen code lived here only as a fixture
# while the display still carried the ones it replaced.
#
# The address serves the committed file as it is, but nothing ties the
# bytes at an address to the bytes measured here: the file can be
# replaced in place, and the address does not change when it is. The
# digest is therefore the identity, and the measurement is attached to
# it.
#
# The code encodes https://www.edgelens.ai and nothing else. The address
# is where the committed copy is served once this repository is public.
#
# The margin is in the file itself. The code is generated with the
# encoder's four-module quiet zone on every side and committed as that
# raster, so what is displayed carries the margin it was measured with.
@dataclass(frozen=True)
class DisplayedCode:
    url: str
    fixture: str
    sha256: str
    modules: int


FEASIBILITY_QR = DisplayedCode(
    url="https://raw.githubusercontent.com/edgelens-ai/edgelens-sdk/main/examples/pytest/fixtures/edgelens-www-qr.png",
    fixture="fixtures/edgelens-www-qr.png",
    sha256="ab4ae0a3e612019d28edadbea7615ec8cfe6f5c53221b2519aac148fca9d7912",
    modules=25,
)

FEASIBILITY_QR_URL = FEASIBILITY_QR.url

# The same code twice, not two codes. Serving it at two sizes was tried
# and taught nothing, because the size it is served at never reaches the
# display. What two photographs of one code still buy is a second reading
# of the same thing — which is what lets the two be compared against each
# other rather than against an expectation, and it costs one allocation
# instead of two. Anything that differs between them is the rig, not the
# code.
FEASIBILITY_QR_CANDIDATES = (FEASIBILITY_QR.url, FEASIBILITY_QR.url)

# The two codes this frame displayed before, kept so that a reader meeting
# one of these payloads in an older run can tell what it was looking at.
# Neither may be displayed again: both are cropped flush to the symbol
# with no quiet zone whatever, which is why neither could be decoded.
RETIRED_FLUSH_CROPPED_PAYLOADS = (
    "http://commons.wikimedia.org/wiki/Main_Page",
    "http://commons.wikimedia.org/",
)

# How many modules across the displayed symbol is, measured from the
# committed bytes rather than derived from the payload length.
FEASIBILITY_QR_MODULES = FEASIBILITY_QR.modules

# The two densities that have been measured on this hardware, in pixels per
# module of the image handed to the decoder: one that failed to decode and
# one that decoded. They are the only numbers available for judging whether
# a capture ever stood a chance, and they are properties of the photograph
# rather than of the display — a figure taken off the panel has the optics
# in between and is a different quantity.
QR_PX_PER_MODULE_MEASURED_FAILING = 4
QR_PX_PER_MODULE_MEASURED_PASSING = 20


def required_capture_span_px(modules: int, px_per_module: int) -> int:
    """How wide the code must appear in the capture to reach that density."""
    return modules * px_per_module


@dataclass(frozen=True)
class DisplayedCodeCheck:
    """Whether some bytes are the artifact a measurement is attached to.

    Not a bool, because a bool is unreportable. The one thing a reader
    needs from a failure here is which image they actually have, and that
    is the pair of digests next to the address they came from — a bare
    False sends them back to the file to work out what was compared with
    what.
    """

    url: str
    expected_sha256: str
    actual_sha256: str
    size_bytes: int

    @property
    def matches(self) -> bool:
        return self.actual_sha256 == self.expected_sha256

    @property
    def mismatch_reason(self) -> str | None:
        """Why these bytes are not the measured artifact, or None."""
        if self.matches:
            return None
        return (
            f"the bytes served at {self.url} are not the artifact the quiet "
            f"zone was measured from: expected sha256 {self.expected_sha256}, "
            f"got {self.actual_sha256} over {self.size_bytes} bytes. The "
            f"file at that address can be replaced without the address "
            f"changing, and every margin figure recorded here is a property "
            f"of the bytes rather than of the address. Photographing "
            f"this would spend the window on a code whose measurement does "
            f"not apply and return a red that means nothing."
        )


def verify_displayed_bytes(data: bytes, code: DisplayedCode) -> DisplayedCodeCheck:
    """Decide whether ``data`` is the artifact ``code`` was measured from.

    Fetches nothing, deliberately. The bytes have to come from somewhere
    with a network, and the offline suite has none — so the comparison
    that decides this lives here where it can be pinned on bytes handed
    straight in, and the one line that reaches the network stays in the
    demo path.

    The committed copy is checked against this digest offline. That is a
    different question and does not answer this one: the device fetches
    the address itself, so the bytes it photographs never pass through
    the harness, and nothing had ever hashed them.
    """
    return DisplayedCodeCheck(
        url=code.url,
        expected_sha256=code.sha256,
        actual_sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
    )


DISPLAY_BYTES_UNVERIFIED = "displayed-artifact-unverified"


def display_bytes_unverified_note(code: DisplayedCode, error: str) -> str:
    """What to report when the served bytes could not be fetched at all.

    A fetch that fails is not a mismatch, and must not end the run. The
    harness's network is not the one the device fetches over, so a blip
    here is evidence about neither the artifact nor the display — and
    stopping on it would turn a recoverable blip into a lost window,
    which costs more than the bug the check exists to catch.

    What it does cost is the check: nothing was compared, so the margin
    figures are unverified for this run, and saying so is the whole
    point. A check that is silent when it did not run reads afterwards
    exactly like a check that passed.
    """
    return (
        f"{DISPLAY_BYTES_UNVERIFIED}: the bytes at {code.url} could not be "
        f"fetched, so nothing was compared against sha256 {code.sha256} and "
        f"the quiet-zone margin recorded for this code is unverified for this "
        f"run: {error}. This is not a mismatch and the run continues. Read "
        f"any margin figure in this run's output as a property of the "
        f"committed copy alone."
    )

MODEL_FILE = "scrfd_500m_kps_int8.cvimodel"
BINARY_FILE = "sscma-model"
CAPTURE_FILE = "capture_jpeg"
DECODER_FILE = "qr_decode"
IMAGE_FILE = "sample_faces.jpg"

# Where the deployed payload lands on reCamaginedOS (device.deploy SCPs
# files into this directory). Capture and result files are written here
# too: deploy proves the directory exists and is writable, which
# ``/userdata/local`` — capture_jpeg's default — does not.
DEVICE_MODEL_DIR = "/userdata/Models"
CAPTURE_PATH = f"{DEVICE_MODEL_DIR}/capture.jpg"
RESULT_PATH = f"{DEVICE_MODEL_DIR}/result.jpg"

# The decoder writes its records to stdout and everything else to stderr,
# and the two must not be folded together. The reason is not tidiness: a
# frame holding a code too small to resolve and a frame of an unlit panel
# produce the same records and the same exit code, and differ only in what
# is written to stderr. Folding the streams would leave the one run that
# can tell those apart unable to.
#
# So stderr goes to a file on the device and is read back after the record,
# behind a marker. That also avoids depending on the platform's own stderr
# channel, which is carried on the exec response and whose behaviour
# through this path has never been measured — committing to it here would
# be a guess settled only once a device is in hand.
QR_STDERR_PATH = f"{DEVICE_MODEL_DIR}/qr_decode.stderr.txt"
QR_DIAGNOSTICS_MARKER = "QR_DECODE_DIAGNOSTICS"

# The capture utility writes a short burst of frames in one run — one
# immediately, the rest at scheduled intervals — and reports what it wrote
# on stdout. A single run is what makes the burst meaningful: starting the
# sensor again restarts whatever it does on startup, so separate runs would
# each measure the same first frame instead of a progression.
#
# ``capture.jpg`` is the last scheduled frame, and it stays the inference
# input. The burst lands beside it as ``capture.fNNN.jpg``, and the run also
# writes ``capture.manifest.txt``. Only the capture utility decides how many
# frames and when; this example passes no schedule and records the one the
# device reports using.
CAPTURE_SERIES_SUFFIX = ".f"
CAPTURE_MANIFEST_SUFFIX = ".manifest.txt"

# How many images are brought back, whatever the burst length. The timings
# are already on stdout — frame number, elapsed time and encoded size per
# frame — so the numbers need no transfer at all. Images are only needed for
# the one thing a number cannot do, which is let a person see what the
# camera saw, and for that the first frame and the last are the comparison.
# Two more are brought back when the sizes show something interesting
# between them.
#
# The bound is deliberately independent of the burst length: a longer burst
# costs device time and never costs transfer. That matters because every
# chunk is a request against a shared per-host rate limit with no retries,
# and an unbounded series would be a self-inflicted failure during the one
# window the run gets.
FETCH_IMAGE_BOUND = 4

# A frame carrying appreciably more encoded detail than the first one is
# where the interesting change happens; a near-flat frame compresses to a
# fraction of a detailed one, so the ratio is a clear signal rather than a
# tuned threshold. The two frames either side of it are the pair worth
# looking at.
KNEE_BYTES_RATIO = 2.0

# capture_jpeg's documented runtime path (solutions/capture_jpeg/README.md).
_CAPTURE_LD_PATH = (
    "/lib:/usr/lib:/usr/lib64:"
    "/mnt/system/lib:/mnt/system/usr/lib:/mnt/system/usr/lib/3rd"
)
# sscma-model's proven runtime path. Deliberately left as it was: this is
# the set a passing run used, and widening it here would change a proven
# invocation for no reason.
_INFER_LD_PATH = "/mnt/system/lib:/mnt/system/usr/lib:/mnt/system/usr/lib/3rd"
# The decoder gets the capture utility's path, which is the instruction
# rather than a convenience: nothing in the decoder supplies a search path
# of its own, and nothing on the image supplies one either. It carries no
# RPATH and no RUNPATH, there is no `/etc/ld-musl-*.path` on the target,
# and the directory holding the OpenCV libraries it needs reaches the
# loader only through `/etc/profile`, which a non-login command over SSH
# does not read. Every library is present and correct on the image and it
# still fails at the loader without this.
_QR_LD_PATH = _CAPTURE_LD_PATH

# device.exec stdout is truncated by the platform at 256 KiB. base64
# inflates 4/3, so a whole-file fetch only works for small files; the
# annotated frame is fetched in ranges instead. 96 KiB of input is
# 131072 base64 characters, half the ceiling, leaving room for the
# command echo and any trailing marker.
FETCH_CHUNK_BYTES = 96 * 1024

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DETECTION = re.compile(
    r"x:\s*(?P<x>-?[\d.]+),\s*y:\s*(?P<y>-?[\d.]+),\s*"
    r"w:\s*(?P<w>-?[\d.]+),\s*h:\s*(?P<h>-?[\d.]+),\s*"
    r"score:\s*(?P<score>[\d.]+)\s*target:\s*(?P<target>\d+)"
)
_TIMING = re.compile(
    r"pre:\s*(?P<pre>\d+)\s*ms,\s*infer:\s*(?P<infer>\d+)\s*ms,\s*post:\s*(?P<post>\d+)\s*ms"
)
_STAT = re.compile(r"^SIZE\s+(?P<size>\d+)\s+SHA256\s+(?P<sha>[0-9a-f]{64})\s*$", re.M)
_ABSENT = re.compile(r"^ABSENT\s+(?P<path>\S+)\s*$", re.M)
_ABSENT_GLOB = re.compile(r"^ABSENT_GLOB\s+(?P<pattern>\S+)\s*$", re.M)
_PATH_STAT = re.compile(
    r"^SIZE\s+(?P<size>\d+)\s+SHA256\s+(?P<sha>[0-9a-f]{64})\s+PATH\s+(?P<path>\S+)\s*$",
    re.M,
)
_PATH_SIZE = re.compile(r"^SIZE\s+(?P<size>\d+)\s+PATH\s+(?P<path>\S+)\s*$", re.M)

# Each record is matched twice on purpose: a loose pattern finds every line
# that claims to be one, and a strict pattern parses it. A line the loose
# pattern finds and the strict one rejects is an error, not a line to skip —
# a record truncated mid-field would otherwise vanish silently and the run
# would look like it captured fewer frames than it did.
_SCHEDULE_LOOSE = re.compile(r"^SCHEDULE\b.*$", re.M)
_SCHEDULE = re.compile(r"^SCHEDULE\s+n=(?P<n>\d+)\s+indices=(?P<indices>[\d,]+)\s*$", re.M)
_CAPTURE_LOOSE = re.compile(r"^CAPTURE\b.*$", re.M)
_CAPTURE = re.compile(
    r"^CAPTURE\s+path=(?P<path>\S+)\s+frame=(?P<frame>\d+)\s+"
    r"elapsed_ms=(?P<elapsed>\d+)\s+bytes=(?P<bytes>\d+)\s*$",
    re.M,
)
_SETTLED_LOOSE = re.compile(r"^SETTLED\b.*$", re.M)
_SETTLED = re.compile(r"^SETTLED\s+path=(?P<path>\S+)\s+frame=(?P<frame>\d+)\s*$", re.M)
_STATUS_LOOSE = re.compile(r"^STATUS\b.*$", re.M)
_STATUS = re.compile(r"^STATUS\s+(?P<status>[A-Z_]+)\s*$", re.M)

# The record keywords the capture utility emits. They are the cheapest
# available evidence that the bundled binary is the one that reports what
# it wrote: an older build captured a single frame and reported nothing,
# so the parser above finds no schedule and raises — and it raises on the
# device, with a session already running, minutes into a run. Checking
# the bytes that ship turns that into a failure here instead, in under a
# second, before anything is allocated.
CAPTURE_RECORD_KEYWORDS = ("SCHEDULE", "CAPTURE", "SETTLED", "STATUS")

CAPTURE_COMPLETE = "COMPLETE"
# The two incomplete outcomes are different findings and must not be
# collapsed: no frame arriving at all points at the sensor or its startup,
# while frames arriving without reaching the last scheduled one points at
# the schedule being shorter than whatever the sensor is doing.
CAPTURE_STATUSES = (
    CAPTURE_COMPLETE,
    "INCOMPLETE_NO_FRAMES",
    "INCOMPLETE_NOT_SETTLED",
)


def models_dir() -> Path:
    """Absolute path to the bundled payload, independent of the cwd."""
    return Path(__file__).resolve().parent.parent / "models"


# The names a run writes. Named here rather than spelled at each write
# site so the tests that plant and check these files read the same names
# the run uses, and cannot end up exercising a filename the run stopped
# writing.
ARTIFACT_RECORDS_NAME = "demo5-capture-records.txt"
ARTIFACT_ACCOUNTING_NAME = "demo5-capture-accounting.txt"
ARTIFACT_RESULT_NAME = "demo5-inference-result.jpg"
# The decoder's two streams, kept as separate files because they answer
# different questions: the records say what was found, and the
# diagnostics are the only thing that separates a code that could not be
# resolved from a display with nothing on it.
ARTIFACT_QR_RECORDS_NAME = "demo-qr-records.txt"
ARTIFACT_QR_DIAGNOSTICS_NAME = "demo-qr-diagnostics.txt"
# What is kept when the two cannot be told apart at all. The split
# refuses output with no marker in it, and that refusal is correct —
# but it leaves a run with neither file, which is the run whose output
# is least understood and most worth having.
ARTIFACT_QR_UNSPLIT_NAME = "demo-qr-unsplit.txt"
PASSWORD_REDACTED = "<session password>"
QR_UNSPLIT_EMPTY_NOTE = "(the decoder produced no output before the split refused it)"
ARTIFACT_FETCHED_PREFIX = "demo5-"

ARTIFACT_RUN_PREFIX = "run-"


def fetched_artifact_name(device_path: str) -> str:
    """Local name for a frame fetched back off the device."""
    return f"{ARTIFACT_FETCHED_PREFIX}{Path(device_path).name}"


def artifact_run_name(when: datetime) -> str:
    return f"{ARTIFACT_RUN_PREFIX}{when.strftime('%Y%m%dT%H%M%SZ')}"


def new_run_dir(base: Path, when: datetime) -> Path:
    """Create and return a directory this run alone writes to.

    The names above are fixed, so runs sharing one directory would mean
    each run overwriting the files of any earlier run that fetched the
    same frames and leaving the rest in place. What is left behind does
    not look left behind: the frames of two runs are all real images
    with valid sizes and matching digests, so together they form a
    plausible picture of a single run. A plausible picture gets believed,
    where a mismatch would get noticed.

    Nothing is deleted to keep runs apart. Clearing the directory first
    is the shorter fix and it destroys evidence: an earlier run's images
    can be the only record of what the device saw, because the device is
    wiped when its session ends.

    Named for the time rather than the session, because the session's
    identifier is not on the client library's public surface and an
    example reaching past the public API to get it would teach the wrong
    lesson — and because a reader looking for their own run wants the
    newest directory, which is the one that sorts last.

    Refuses to reuse a directory that already exists rather than merging
    into it. Two runs inside one second is not a case anyone expects,
    and a scheme that silently merges on collision has not namespaced
    anything — it has moved the same defect somewhere less likely and
    harder to notice.
    """
    base.mkdir(parents=True, exist_ok=True)
    name = artifact_run_name(when)
    candidate = base / name
    attempt = 1
    while True:
        try:
            candidate.mkdir(exist_ok=False)
            return candidate
        except FileExistsError:
            attempt += 1
            candidate = base / f"{name}-{attempt}"


def missing_record_keywords(data: bytes) -> tuple[str, ...]:
    """Which record keywords a capture binary does not contain.

    Deliberately a check on the bytes rather than on a digest. A digest
    pin would have to be edited by hand after every legitimate rebuild,
    and a check that has to be edited to keep passing is one the next
    reader deletes. These keywords are the behaviour being relied on, so
    a build that still has them is still usable and a build that has lost
    them is not, whoever rebuilt it and whenever.
    """
    return tuple(k for k in CAPTURE_RECORD_KEYWORDS if k.encode() not in data)


@dataclass(frozen=True)
class Payload:
    """The files device.deploy pushes to the camera."""

    model: Path
    inference_binary: Path
    capture_binary: Path
    decoder_binary: Path
    sample_image: Path

    def as_files(self) -> list[str]:
        """Everything but the model — device.deploy takes it separately."""
        return [
            str(self.inference_binary),
            str(self.capture_binary),
            str(self.decoder_binary),
            str(self.sample_image),
        ]

    def all_paths(self) -> tuple[Path, ...]:
        return (
            self.model,
            self.inference_binary,
            self.capture_binary,
            self.decoder_binary,
            self.sample_image,
        )


def payload_paths() -> Payload:
    d = models_dir()
    return Payload(
        model=d / MODEL_FILE,
        inference_binary=d / BINARY_FILE,
        capture_binary=d / CAPTURE_FILE,
        decoder_binary=d / DECODER_FILE,
        sample_image=d / IMAGE_FILE,
    )


def capture_stem(output_path: str = CAPTURE_PATH) -> str:
    """The naming base every artifact of a capture run derives from.

    Knowing it means the whole set a run will write is known *before* the
    run, which is what lets the previous run's files be deleted and proved
    gone first. Nothing here is ever reconstructed afterwards: what came
    back is read from what the device reported writing.
    """
    suffix = ".jpg"
    if output_path.endswith(suffix):
        return output_path[: -len(suffix)]
    return output_path


def capture_series_glob(output_path: str = CAPTURE_PATH) -> str:
    """Pattern covering the burst, whose length is not known in advance."""
    return f"{capture_stem(output_path)}{CAPTURE_SERIES_SUFFIX}*.jpg"


def capture_manifest_path(output_path: str = CAPTURE_PATH) -> str:
    return f"{capture_stem(output_path)}{CAPTURE_MANIFEST_SUFFIX}"


def capture_output_paths(
    output_path: str = CAPTURE_PATH, result_path: str = RESULT_PATH
) -> tuple[tuple[str, ...], str]:
    """Everything a run writes: exact paths, plus the burst's pattern.

    The manifest is in here with the images. It is written by the same run
    and left behind by a failed one exactly as the images are, so leaving
    it out would let a previous run's index survive into this one.
    """
    return (
        (output_path, capture_manifest_path(output_path), result_path),
        capture_series_glob(output_path),
    )


def _sudo(session_password: str, inner: str) -> str:
    """Run ``inner`` as root, folding stderr into stdout.

    ``sudo -S`` reads the password from stdin (one line), then the command
    inherits an empty stdin. This is the single place the demo puts the
    per-session password on a command line; the platform's ``exec`` has no
    stdin channel, so there is nowhere else to put it today. Keep it that
    way — one call site is what makes replacing the mechanism a one-line
    change.
    """
    return f"echo {shlex.quote(session_password)} | sudo -S -E sh -c {shlex.quote(inner)} 2>&1"


def preflight_command(
    session_password: str,
    output_path: str = CAPTURE_PATH,
    result_path: str = RESULT_PATH,
) -> str:
    """Delete everything a run writes, then prove it is gone.

    The capture utility opens each output file only once a frame arrives,
    so every failure route leaves whatever was already at that path in
    place, and a short write leaves a partial file. The exit code is right
    in all of those cases and the file on disk is not, so an image from an
    earlier attempt would read as a successful capture. Proving absence
    first is what makes presence afterwards mean something.

    The burst is cleared by pattern, because how many frames a run writes
    is the capture utility's decision and is not known here. Clearing only
    the settled frame's own name would leave a whole previous burst in
    place — and those files would pass every later check, because they are
    real images with matching digests. They would just be from the wrong
    run.

    Emits ``ABSENT <path>`` per exact path that is gone,
    ``ABSENT_GLOB <pattern>`` when nothing matches the burst pattern, and
    ``PRESENT <path> SHA256 <digest>`` for anything that survives.
    """
    exact, series = capture_output_paths(output_path, result_path)
    checks = "; ".join(
        f'rm -f {p}; if [ -e {p} ]; then printf "PRESENT %s SHA256 " {p}; '
        f'sha256sum {p} | cut -d" " -f1; else echo "ABSENT {p}"; fi'
        for p in exact
    )
    # An unmatched pattern stays literal in POSIX sh, and `-e` on the
    # literal pattern is false, so the loop reports nothing left and the
    # ABSENT_GLOB line is what proves the sweep ran rather than matched.
    sweep = (
        f'rm -f {series}; left=0; for q in {series}; do '
        f'if [ -e "$q" ]; then printf "PRESENT %s SHA256 " "$q"; '
        f'sha256sum "$q" | cut -d" " -f1; left=1; fi; done; '
        f'if [ "$left" = 0 ]; then echo "ABSENT_GLOB {series}"; fi'
    )
    inner = (
        f"cd {DEVICE_MODEL_DIR} && ls -l && "
        f'touch .writable && rm -f .writable && echo "WRITABLE {DEVICE_MODEL_DIR}"; '
        f"{checks}; {sweep}"
    )
    return _sudo(session_password, inner)


def capture_command(session_password: str, output_path: str = CAPTURE_PATH) -> str:
    """Run the capture burst and let it report what it wrote.

    No frame schedule is passed. How many frames to take and when is the
    capture utility's own decision, and it echoes the schedule it used, so
    this example keeps no second copy of that value to drift out of step
    with it. An operator re-aiming the burst does it by invoking the
    utility directly, not by changing a constant here.

    device.deploy SCPs files in without the executable bit, so the
    uploaded binary is marked runnable first.
    """
    d = DEVICE_MODEL_DIR
    inner = (
        f"chmod +x {d}/{CAPTURE_FILE} && "
        f"LD_LIBRARY_PATH={_CAPTURE_LD_PATH} {d}/{CAPTURE_FILE} {output_path}; "
        f'rc=$?; echo "EXIT $rc"; exit $rc'
    )
    return _sudo(session_password, inner)


def listing_command(
    session_password: str, paths: list[str], digest_paths: list[str]
) -> str:
    """Measure every path, and hash the ones that are coming back.

    ``SIZE <bytes> PATH <path>`` for a path that is only measured,
    ``SIZE <bytes> SHA256 <digest> PATH <path>`` for one that is also
    hashed, and ``ABSENT <path>`` for one that is not there.

    Both answers in one call, because nothing makes them two. Which
    images come back is decided from the sizes the capture run already
    reported on its own stdout, so the hash set is known before anything
    is measured — the apparent dependency that would force a second round
    trip is not there. Each command is a request against a shared
    per-host rate limit with no retries, so a second one costs a share of
    the run's budget and buys nothing.

    The two measurements answer different questions and are deliberately
    taken by different means. The size here is the file as it exists,
    which compared against the capture run's own accounting catches a
    write that stopped early — the only check that can see that in a
    frame which never comes back. The digest is computed by a different
    program than the one that wrote the bytes, which is what makes it
    evidence that the bytes which arrived are the bytes on the device.

    Paths are quoted individually. They come from the device rather than
    from this file, and the device is customer hardware: the password and
    the command body are already quoted, and leaving the paths out of
    that would be the one gap in an otherwise closed discipline.
    """
    wanted = set(digest_paths)
    parts = []
    for p in paths:
        q = shlex.quote(p)
        if p in wanted:
            parts.append(
                f'if [ -e {q} ]; then printf "SIZE %s SHA256 " "$(wc -c < {q})"; '
                f'printf "%s PATH %s\\n" "$(sha256sum {q} | cut -d" " -f1)" {q}; '
                f'else printf "ABSENT %s\\n" {q}; fi'
            )
        else:
            parts.append(
                f'if [ -e {q} ]; then printf "SIZE %s PATH %s\\n" '
                f'"$(wc -c < {q})" {q}; '
                f'else printf "ABSENT %s\\n" {q}; fi'
            )
    return _sudo(session_password, "; ".join(parts))


def inference_command(
    session_password: str,
    input_path: str = CAPTURE_PATH,
    output_path: str = RESULT_PATH,
) -> str:
    """Run the face detector over ``input_path``, annotating ``output_path``."""
    d = DEVICE_MODEL_DIR
    inner = (
        f"chmod +x {d}/{BINARY_FILE} && "
        f"LD_LIBRARY_PATH={_INFER_LD_PATH} "
        f"{d}/{BINARY_FILE} {d}/{MODEL_FILE} {input_path} {output_path}; "
        f'rc=$?; echo "EXIT $rc"; '
        f'if [ -e {output_path} ]; then printf "SIZE %s SHA256 " '
        f'"$(wc -c < {output_path})"; sha256sum {output_path} | cut -d" " -f1; '
        f'else echo "ABSENT {output_path}"; fi; exit $rc'
    )
    return _sudo(session_password, inner)


def bundled_inference_command(session_password: str) -> str:
    """The old bundled-JPEG run, kept as a model-correctness check.

    Not the demo: it never touches the sensor. It stays here because the
    detections it produces are the fixture the offline parser tests use.
    """
    return inference_command(
        session_password,
        input_path=f"{DEVICE_MODEL_DIR}/{IMAGE_FILE}",
        output_path=f"{DEVICE_MODEL_DIR}/bundled_result.jpg",
    )


def qr_decode_command(
    session_password: str,
    image_path: str = CAPTURE_PATH,
    stderr_path: str = QR_STDERR_PATH,
) -> str:
    """Decode ``image_path`` on the device, keeping the two streams apart.

    The decoder takes exactly one argument and rejects any other count
    with a usage message and the same exit code it uses for a local
    resource failure, so that code carries no cause of its own. Keeping
    the diagnostics is therefore what makes the difference between a run
    that establishes something and a run that only went red: the three
    outcomes worth telling apart — it decoded, it read the frame and
    found nothing it could use, it never ran at all — are not separable
    from the records and the exit code alone.

    The diagnostics file is removed before the decoder runs and read back
    after it, so what comes back belongs to this invocation. Without that
    an earlier attempt's message survives at the same path and reads as
    this one's, which is the same reasoning the capture preflight applies
    to frames.

    One invocation, because the marker is printed unconditionally after
    it: a second call would spend a share of a shared rate limit that has
    no retries to buy a line already on its way back.

    Nothing echoes the exit code onto stdout, unlike every other command
    here, and that is a requirement rather than an omission. The reader
    of these records refuses any output after the status line, because a
    status that is not last cannot be told from a report that was cut
    short — so a code echoed there would fail every decode. The exit code
    is already carried back as its own field on the exec result, which is
    where the reader takes it from.

    The image path is quoted because it need not come from this file — a
    run decodes the frame the capture utility reported writing, and that
    name arrives from the device.
    """
    d = DEVICE_MODEL_DIR
    q = shlex.quote(image_path)
    e = shlex.quote(stderr_path)
    inner = (
        f"rm -f {e}; "
        f"chmod +x {d}/{DECODER_FILE} && "
        f"LD_LIBRARY_PATH={_QR_LD_PATH} {d}/{DECODER_FILE} {q} 2> {e}; "
        f'rc=$?; echo "{QR_DIAGNOSTICS_MARKER}"; '
        f"if [ -e {e} ]; then cat {e}; fi; exit $rc"
    )
    return _sudo(session_password, inner)


def split_qr_output(stdout: str) -> tuple[str, str]:
    """(records, diagnostics) from one decode command's output.

    Raises when the marker is absent. A missing marker means the output
    stopped before the decoder's own stderr was read back, and the half
    that arrived cannot be told from a whole one: treating it as a
    complete report with nothing on stderr would turn a truncated run
    into a clean one, which is the single reading this split exists to
    prevent.
    """
    lines = without_password_prompt(stdout).split("\n")
    # Matched as a whole line rather than as a substring, so a decoded
    # payload that happened to contain the marker's text could not split
    # the output. What is in front of the camera is not ours to assume.
    for number, line in enumerate(lines):
        if line == QR_DIAGNOSTICS_MARKER:
            return "\n".join(lines[:number]), "\n".join(lines[number + 1 :])
    raise ValueError(
        f"no {QR_DIAGNOSTICS_MARKER} line in the decoder's output, so the "
        f"records cannot be told apart from its diagnostics and a truncated "
        f"report would read as a complete one:\n{stdout[:500]}"
    )


def stat_command(session_password: str, path: str) -> str:
    """``SIZE <bytes> SHA256 <digest>``, or ``ABSENT <path>``."""
    inner = (
        f'if [ -e {path} ]; then printf "SIZE %s SHA256 " "$(wc -c < {path})"; '
        f'sha256sum {path} | cut -d" " -f1; else echo "ABSENT {path}"; fi'
    )
    return _sudo(session_password, inner)


def fetch_chunk_command(
    session_password: str, path: str, offset: int, length: int
) -> str:
    """base64 of ``length`` bytes of ``path`` from ``offset``.

    ``dd`` with a 1-byte block size is slow but exact; the files here are
    a few hundred KiB, and an off-by-one in the range arithmetic would
    corrupt the image in a way no exit code reports.

    The path is quoted because it comes from the device, not from here.
    """
    inner = (
        f"dd if={shlex.quote(path)} bs=1 skip={offset} count={length} "
        f"2>/dev/null | base64"
    )
    return _sudo(session_password, inner)


def parse_stat(stdout: str) -> tuple[int, str]:
    """(size, sha256) from a stat/capture/inference command's output."""
    absent = _ABSENT.search(stdout)
    if absent is not None:
        raise FileNotFoundError(f"device reports no file at {absent['path']}")
    m = _STAT.search(stdout)
    if m is None:
        raise ValueError(f"no SIZE/SHA256 line in output:\n{stdout[:500]}")
    return int(m["size"]), m["sha"]


def parse_absent(stdout: str) -> list[str]:
    """The paths a preflight command proved gone."""
    return [m["path"] for m in _ABSENT.finditer(stdout)]


def parse_absent_globs(stdout: str) -> list[str]:
    """The patterns a preflight command proved nothing matches."""
    return [m["pattern"] for m in _ABSENT_GLOB.finditer(stdout)]


def without_password_prompt(stdout: str) -> str:
    """Drop sudo's prompt from the front of the output.

    The prompt has no trailing newline, so the first line of real output
    arrives glued to it. Every record below is matched at the start of a
    line, so a glued first line would simply not be seen — and the first
    line is where the schedule and the earliest frame are.
    """
    return re.sub(r"\APassword:\s*", "", stdout)


def without_session_password(text: str, password: str) -> str:
    """``text`` with the session password replaced wherever it appears.

    Not a theoretical guard. Every privileged command is built as
    ``echo <password> | sudo -S …``, so the value is on the device's
    command line, and a shell that echoes a line it could not parse puts
    it on stdout — from where anything written to the artifacts
    directory would carry it. ``sudo -S`` itself does not echo, which is
    why no artifact has ever held it; that is a property of sudo rather
    than of this harness, and this is the part that does not depend on
    it staying true.
    """
    return text.replace(password, PASSWORD_REDACTED) if password else text


def unsplit_artifact_text(stdout: str) -> str:
    """What to keep when the decoder's output cannot be divided.

    Sudo's prompt comes off before any of this reaches the filesystem.
    The artifacts directory is gitignored, which is one edit away from
    not being, and the prompt is the one part of this stream that sits
    next to a credential.

    An empty result is written as a note rather than as an empty file: a
    file that is empty and a file that was never written look identical
    in a directory listing and mean opposite things — the decoder said
    nothing, versus nobody asked it.
    """
    text = without_password_prompt(stdout)
    return text if text.strip() else QR_UNSPLIT_EMPTY_NOTE


def parse_sizes(stdout: str) -> dict[str, int]:
    """``{path: size}`` for every measured path. Raises if any is absent.

    Reads the hashed lines as well as the measured-only ones. The
    listing covers every reported path in one call and only some of them
    carry a digest, so a reader that looked at one line shape would
    silently return sizes for part of the set — and the short-write check
    would then pass by having nothing to compare for the rest.
    """
    stdout = without_password_prompt(stdout)
    missing = parse_absent(stdout)
    if missing:
        raise FileNotFoundError(f"device reports no file at {', '.join(missing)}")
    sizes = {m["path"]: int(m["size"]) for m in _PATH_SIZE.finditer(stdout)}
    sizes.update({m["path"]: int(m["size"]) for m in _PATH_STAT.finditer(stdout)})
    if not sizes:
        raise ValueError(f"no SIZE/PATH lines in output:\n{stdout[:500]}")
    return sizes


def parse_digests(stdout: str) -> dict[str, tuple[int, str]]:
    """``{path: (size, sha256)}``. Raises if anything is absent."""
    stdout = without_password_prompt(stdout)
    missing = parse_absent(stdout)
    if missing:
        raise FileNotFoundError(f"device reports no file at {', '.join(missing)}")
    out = {m["path"]: (int(m["size"]), m["sha"]) for m in _PATH_STAT.finditer(stdout)}
    if not out:
        raise ValueError(f"no SIZE/SHA256/PATH lines in output:\n{stdout[:500]}")
    return out


@dataclass(frozen=True)
class CaptureFrame:
    """One frame the capture run reported writing.

    ``size_bytes`` is the capture utility's own accounting of what it
    wrote, which is why it is worth having: compared against the file's
    measured size it catches a write that stopped early, and nothing else
    in this example can see that.
    """

    path: str
    frame: int
    elapsed_ms: int
    size_bytes: int


@dataclass(frozen=True)
class CaptureReport:
    """Everything a capture run said about itself."""

    schedule: tuple[int, ...]
    frames: tuple[CaptureFrame, ...]
    settled_path: str | None
    settled_frame: int | None
    status: str

    @property
    def complete(self) -> bool:
        return self.status == CAPTURE_COMPLETE

    def frame_at(self, index: int) -> CaptureFrame | None:
        for f in self.frames:
            if f.frame == index:
                return f
        return None

    def in_order(self) -> tuple[CaptureFrame, ...]:
        return tuple(sorted(self.frames, key=lambda f: f.frame))


def _one_line(stdout: str, loose: re.Pattern, strict: re.Pattern, label: str):
    found = loose.findall(stdout)
    if not found:
        raise ValueError(f"no {label} line in capture output:\n{stdout[:500]}")
    if len(found) > 1:
        raise ValueError(f"{len(found)} {label} lines in capture output, expected one")
    m = strict.search(stdout)
    if m is None:
        raise ValueError(f"malformed {label} line: {found[0]!r}")
    return m


def parse_capture_report(stdout: str) -> CaptureReport:
    """Parse what the capture run reported, or raise.

    What this refuses matters more than what it accepts, because every
    shape it refuses is one that would otherwise read as a smaller but
    perfectly successful run — a truncated record looks like a frame that
    was never taken, and a run that quietly reports six frames instead of
    fourteen looks like a shorter burst rather than a broken one.

    So each kind of record is found by a loose pattern and parsed by a
    strict one, and a line that the loose pattern finds while the strict
    one rejects is an error. Skipping it would be the silent failure.
    """
    stdout = without_password_prompt(stdout)
    sched = _one_line(stdout, _SCHEDULE_LOOSE, _SCHEDULE, "SCHEDULE")
    schedule = tuple(int(x) for x in sched["indices"].split(","))
    declared = int(sched["n"])
    if len(schedule) != declared:
        raise ValueError(
            f"schedule declares n={declared} but lists {len(schedule)} indices: "
            f"{sched['indices']!r}"
        )

    loose = _CAPTURE_LOOSE.findall(stdout)
    strict = list(_CAPTURE.finditer(stdout))
    if len(strict) != len(loose):
        bad = [line for line in loose if _CAPTURE.search(line) is None]
        raise ValueError(f"malformed CAPTURE record(s): {bad}")

    frames = tuple(
        CaptureFrame(
            path=m["path"],
            frame=int(m["frame"]),
            elapsed_ms=int(m["elapsed"]),
            size_bytes=int(m["bytes"]),
        )
        for m in strict
    )
    seen: set[int] = set()
    for f in frames:
        if f.frame in seen:
            raise ValueError(f"frame {f.frame} reported more than once")
        seen.add(f.frame)
    if len({f.path for f in frames}) != len(frames):
        raise ValueError("two CAPTURE records report the same path")

    status = _one_line(stdout, _STATUS_LOOSE, _STATUS, "STATUS")["status"]
    if status not in CAPTURE_STATUSES:
        raise ValueError(
            f"unknown capture status {status!r}; expected one of "
            f"{', '.join(CAPTURE_STATUSES)}"
        )

    settled_path: str | None = None
    settled_frame: int | None = None
    if _SETTLED_LOOSE.findall(stdout):
        m = _one_line(stdout, _SETTLED_LOOSE, _SETTLED, "SETTLED")
        settled_path, settled_frame = m["path"], int(m["frame"])

    if status == CAPTURE_COMPLETE:
        # Which frame settled is read from the record and never from where
        # it appeared. The last line, the highest index and the last
        # scheduled entry all happen to be right most of the time, which
        # is exactly what makes them dangerous to rely on.
        if settled_path is None:
            raise ValueError(
                "capture reported COMPLETE with no SETTLED record, so which "
                "frame is the settled one is unknown. It is not safe to "
                "assume the last or highest-numbered record: that assumption "
                "is right until the one run where it is not."
            )
        if settled_frame not in seen:
            raise ValueError(
                f"SETTLED names frame {settled_frame}, which has no CAPTURE record"
            )
        if len(frames) != declared:
            raise ValueError(
                f"capture reported COMPLETE with {len(frames)} frames against a "
                f"declared schedule of {declared}"
            )
        if frames and min(f.frame for f in frames) != schedule[0]:
            raise ValueError(
                f"the first scheduled frame {schedule[0]} has no record; the "
                f"lowest reported is {min(f.frame for f in frames)}"
            )

    return CaptureReport(
        schedule=schedule,
        frames=frames,
        settled_path=settled_path,
        settled_frame=settled_frame,
        status=status,
    )


def paths_not_cleared(
    report: CaptureReport, absent: list[str], absent_globs: list[str]
) -> tuple[str, ...]:
    """Reported paths the preflight never proved gone.

    A path the run wrote that the preflight never cleared might be left
    over from an earlier run, and there is no way to tell from the file:
    it is a real image with a size and a digest that agree. Catching it
    here is the only place the distinction still exists.
    """
    claimed = [f.path for f in report.frames]
    if report.settled_path is not None:
        claimed.append(report.settled_path)
    return tuple(
        p
        for p in claimed
        if p not in absent
        and not any(fnmatch.fnmatch(p, g) for g in absent_globs)
    )


def unmeasured_paths(claimed: list[str], on_disk: dict[str, int]) -> tuple[str, ...]:
    """Reported paths the listing returned no size for.

    The comparison below can only report a disagreement about a path it
    was given a size for, so on its own it is satisfied by a listing that
    covered almost nothing: fewer measurements mean fewer disagreements.
    This supplies the denominator. A reported path with no measured size
    is a failure and not a skip, because the check that is supposed to
    catch a short write cannot run on it at all.
    """
    return tuple(p for p in claimed if p not in on_disk)


def size_disagreements(
    report: CaptureReport, on_disk: dict[str, int]
) -> tuple[tuple[str, int, int], ...]:
    """Frames whose reported size is not the size of the file.

    ``(path, reported, measured)`` for each. The capture utility counts
    what it handed to the filesystem; this is what the filesystem kept. A
    write that stopped early leaves a shorter file and a correct exit code,
    and for the frames that are never brought back nothing else can see it.
    """
    out = []
    for f in report.frames:
        measured = on_disk.get(f.path)
        if measured is not None and measured != f.size_bytes:
            out.append((f.path, f.size_bytes, measured))
    return tuple(out)


def accounting_table(report: CaptureReport, plan: FetchPlan) -> str:
    """The whole account of a run, as a file that outlives the device.

    One row per reported frame with its number, timing, encoded size,
    whether it came back and — when it did not — why. The reasons are the
    part that has to be durable: a frame left behind deliberately and a
    frame nobody noticed are indistinguishable afterwards, and the device
    is released and wiped minutes later.
    """
    reasons = dict(plan.skipped)
    indices = ",".join(str(i) for i in report.schedule)
    lines = [
        f"status\t{report.status}",
        f"schedule\tn={len(report.schedule)}\tindices={indices}",
        f"settled\tframe={report.settled_frame}\t{report.settled_path or '-'}",
        f"bound\t{FETCH_IMAGE_BOUND} images\tknee_frame={plan.knee_frame}",
        "",
        "frame\telapsed_ms\tbytes\tfetched\tpath\treason",
    ]
    for f in report.in_order():
        fetched = "yes" if f.path in plan.fetch else "no"
        lines.append(
            f"{f.frame}\t{f.elapsed_ms}\t{f.size_bytes}\t{fetched}\t{f.path}\t"
            f"{reasons.get(f.path, '')}"
        )
    known = {f.path for f in report.frames}
    if report.settled_path is not None and report.settled_path not in known:
        fetched = "yes" if report.settled_path in plan.fetch else "no"
        lines.append(
            f"-\t-\t-\t{fetched}\t{report.settled_path}\t"
            f"{reasons.get(report.settled_path, 'the settled frame')}"
        )
    return "\n".join(lines) + "\n"


def fetched_length_disagreements(
    report: CaptureReport, fetched: dict[str, int]
) -> tuple[tuple[str, int, int], ...]:
    """Frames whose reported size is not the number of bytes that arrived.

    ``(path, reported, received)`` for each. Separate from the on-disk
    comparison and from the digest on purpose: this one asks whether what
    came back is as long as the camera said it wrote, which is the
    question a digest answers only after the fact and only for the bytes
    it was given. Comparing the arrival against the *listing* instead
    would compare two measurements taken by the same means and would not
    involve the camera's own account at all.
    """
    out = []
    for f in report.frames:
        received = fetched.get(f.path)
        if received is not None and received != f.size_bytes:
            out.append((f.path, f.size_bytes, received))
    return tuple(out)


@dataclass(frozen=True)
class FetchPlan:
    """Which reported images come back, and why the rest do not.

    Every reported frame appears in exactly one of the two lists. That is
    the point of carrying the skipped ones with their reasons rather than
    just taking a subset: a frame that is deliberately left on the device
    and a frame that was quietly forgotten look identical afterwards, and
    only one of them is acceptable.
    """

    fetch: tuple[str, ...]
    skipped: tuple[tuple[str, str], ...]
    knee_frame: int | None

    def accounts_for(self, report: CaptureReport) -> bool:
        claimed = {f.path for f in report.frames}
        if report.settled_path is not None:
            claimed.add(report.settled_path)
        return claimed == set(self.fetch) | {p for p, _ in self.skipped}


def plan_capture_fetch(report: CaptureReport) -> FetchPlan:
    """Choose the images to bring back, by a rule rather than a judgement.

    The first frame and the settled frame always come back: they are the
    comparison a person is being asked to make. Two more come back only
    when the reported sizes show the encoded detail rising sharply
    somewhere between them, and then it is the pair either side of that
    rise — the frames that bracket the change rather than ones chosen near
    it.

    The rule is a function of the reported sizes alone, so the same run
    always selects the same frames. That matters more than picking the
    best pair: a selection made by eye at the time is one nobody can
    reproduce afterwards.
    """
    ordered = report.in_order()
    if not ordered:
        return FetchPlan(fetch=(), skipped=(), knee_frame=None)

    first = ordered[0]
    chosen: list[str] = [first.path]
    reasons: dict[str, str] = {}

    settled_twin = (
        report.frame_at(report.settled_frame)
        if report.settled_frame is not None
        else None
    )
    if report.settled_path is not None:
        chosen.append(report.settled_path)
        if settled_twin is not None:
            reasons[settled_twin.path] = (
                "the settled frame, brought back under its own name instead"
            )

    knee_frame: int | None = None
    baseline = first.size_bytes
    for previous, current in zip(ordered, ordered[1:]):
        if baseline > 0 and current.size_bytes > KNEE_BYTES_RATIO * baseline:
            knee_frame = current.frame
            for f in (previous, current):
                if f.path not in chosen and f.path not in reasons:
                    chosen.append(f.path)
            break

    if len(chosen) > FETCH_IMAGE_BOUND:
        raise AssertionError(
            f"the fetch plan selected {len(chosen)} images against a bound of "
            f"{FETCH_IMAGE_BOUND}: {chosen}"
        )

    for f in ordered:
        if f.path in chosen or f.path in reasons:
            continue
        reasons[f.path] = (
            "not fetched: outside the bound of "
            f"{FETCH_IMAGE_BOUND} images. Its frame number, elapsed time and "
            "encoded size are in the run's records, which is what the "
            "measurement needs; the image itself stays on the device."
        )

    return FetchPlan(
        fetch=tuple(chosen),
        skipped=tuple((p, reasons[p]) for p in reasons),
        knee_frame=knee_frame,
    )


def decode_chunk(stdout: str) -> bytes:
    """Decode one fetch_chunk_command output.

    Raises if the platform truncated the stream — a truncated base64 body
    decodes to plausible-looking bytes, so this has to be checked rather
    than inferred from the length.
    """
    if "output truncated" in stdout:
        raise ValueError("platform truncated the exec output; chunk too large")
    body = ""
    for line in stdout.splitlines():
        line = line.strip()
        # The sudo prompt has no trailing newline, so the first payload line
        # arrives glued to it. Dropping the whole line discards real bytes.
        if line.startswith("Password:"):
            line = line[len("Password:"):].strip()
        if line:
            body += line
    return base64.b64decode(body, validate=True)


# Below this, a returned frame carries too little information to be a
# photograph of anything, and nobody should be asked to look at it.
#
# The two anchors are measured, not chosen. A run that photographed an unlit
# screen returned 15605 bytes at 640x640 — 0.30 bits/pixel — annotation boxes
# and JPEG overhead included; that is the failure this threshold exists to
# catch, and it is NOT negligibly small, which is why the bar cannot simply be
# "a few KB". The annotated reference frame in ``models/`` is 82585 bytes at
# the same 640x640 from the same pipeline — 1.61 bits/pixel. 0.7 sits a factor
# of ~2.3 clear of each.
BLANK_BITS_PER_PIXEL = 0.7

# The size both of those anchors were measured at, and the threshold means
# nothing away from it. The measure is per-pixel, so spreading the same detail
# over more pixels lowers it: the reference frame above scores 1.61 here and
# 0.32 at 1920x1080 — under the threshold, and within a few percent of what the
# blank frame scores. Re-measure both anchors before using it at another size.
ANCHOR_FRAME_SIZE = (640, 640)


def bits_per_pixel(size_bytes: int, width: int, height: int) -> float:
    """How many bits of compressed JPEG there are per pixel.

    A flat field — an unlit screen, a closed shutter, a sensor that never
    produced a frame — compresses to almost nothing, because there is almost
    nothing in it. Real scene detail does not. So this separates "a picture of
    something" from "a picture of nothing" using only the compressed size,
    which keeps the example free of an image-decoding dependency.

    What this is NOT: any judgement about what is in the frame. It does not
    look for faces and it does not use the model's output. It answers one
    question — is there enough information here to be worth a human's time —
    and everything about the content of the picture is left to the person
    looking at it.

    Two limits, stated because a threshold invites over-reading. A dark frame
    full of sensor noise compresses larger than a clean flat one, so this
    catches degenerate frames rather than every unusable one; a frame that
    passes is worth looking at, not proven good. And the result is per-pixel,
    so it is not comparable across frame sizes — the same picture scores lower
    the larger it is. A threshold is only meaningful against anchors measured
    at the size being judged, which is what ``ANCHOR_FRAME_SIZE`` records.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"bad dimensions {width}x{height}")
    return 8.0 * size_bytes / (width * height)


def annotated_frame_refusal(size_bytes: int, width: int, height: int) -> str | None:
    """Why the annotated result cannot be shown to anyone, or None.

    Two refusals, and keeping them apart is the whole value. One says the
    threshold does not apply to a frame this size and therefore nothing is
    known about the picture. The other says the threshold does apply and
    the picture has nothing in it. Collapsing them would report a frame
    nobody could judge as a frame that was judged and found empty.

    Here rather than inline at the call site so a test can reach it. A
    test that re-derived the arithmetic instead would pass whether or not
    the run still consults this, so it would check nothing about the
    code that actually decides.
    """
    if (width, height) != ANCHOR_FRAME_SIZE:
        return (
            f"the returned frame is {width}x{height}, measured at "
            f"{ANCHOR_FRAME_SIZE[0]}x{ANCHOR_FRAME_SIZE[1]}. The blank-frame "
            f"threshold is per-pixel and does not carry across sizes — the "
            f"same picture scores lower the larger it is — so it cannot judge "
            f"this frame. Re-measure both anchors at this size before "
            f"trusting it. Nothing is known to be wrong with the picture."
        )
    density = bits_per_pixel(size_bytes, width, height)
    if density < BLANK_BITS_PER_PIXEL:
        return (
            f"the returned frame is blank: the annotated result at "
            f"{width}x{height} is {density:.3f} bits/pixel, below "
            f"{BLANK_BITS_PER_PIXEL}. The camera photographed something "
            f"with no detail in it — an unlit or unchanged display is the "
            f"usual cause. There is nothing in it to see."
        )
    return None


def jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """(width, height) from a JPEG's start-of-frame marker.

    Hand-rolled to keep the example free of an image dependency: a
    customer copying this example should not have to install Pillow to
    read two integers. Raises if the bytes are not a JPEG, which is also
    the check that the fetched file is an image at all.
    """
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("not a JPEG: missing SOI marker")
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        # SOF0..SOF3, SOF5..SOF7, SOF9..SOF11, SOF13..SOF15
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            height = int.from_bytes(data[i + 5:i + 7], "big")
            width = int.from_bytes(data[i + 7:i + 9], "big")
            return width, height
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    raise ValueError("no start-of-frame marker in JPEG")


@dataclass(frozen=True)
class Detection:
    """One box the model emitted. Centre and size, normalised to the frame."""

    x: float
    y: float
    w: float
    h: float
    score: float
    target: int

    @property
    def invalid_reason(self) -> str | None:
        """Why this is not a rectangle lying inside the frame, or None.

        The one place validity is decided. A box with a negative height
        is not a small box or an uncertain one; it is not a shape. The
        same goes for one wider than the frame it was found in. Counting
        such a thing as a candidate reports a detection where the model
        has told us something went wrong.
        """
        if self.w <= 0:
            return f"width {self.w:.6f} is not positive"
        if self.h <= 0:
            return f"height {self.h:.6f} is not positive"
        left, right = self.x - self.w / 2.0, self.x + self.w / 2.0
        top, bottom = self.y - self.h / 2.0, self.y + self.h / 2.0
        if left < 0.0 or top < 0.0 or right > 1.0 or bottom > 1.0:
            return (
                f"box ({left:.6f}, {top:.6f})-({right:.6f}, {bottom:.6f}) "
                f"is not contained in the frame"
            )
        return None

    @property
    def is_valid(self) -> bool:
        return self.invalid_reason is None


@dataclass(frozen=True)
class InferenceResult:
    # Every box the model emitted, valid or not. Kept whole on purpose: a
    # detector can emit boxes that are not shapes, those are not
    # detections, and a filter that drops them silently is how that stops
    # being noticed. Report both.
    detections: list[Detection]
    pre_ms: int
    infer_ms: int
    post_ms: int

    @property
    def candidates(self) -> list[Detection]:
        """The emitted boxes that are rectangles inside the frame."""
        return [d for d in self.detections if d.is_valid]

    @property
    def rejected(self) -> list[tuple[Detection, str]]:
        """The rest, each with the reason, so none disappears unreported."""
        return [
            (d, reason)
            for d in self.detections
            for reason in [d.invalid_reason]
            if reason is not None
        ]

    def faces(self, min_score: float = 0.5) -> list[Detection]:
        """Scoring candidates. Boxes that are not shapes are not faces."""
        return [d for d in self.candidates if d.score >= min_score]


def parse_inference(stdout: str) -> InferenceResult:
    """Parse ``sscma-model`` output — ANSI-coloured ``I`` log lines, a
    sudo ``Password:`` prompt echo, plain detection lines, one timing
    line. Raises ``ValueError`` if no timing line is present (the run
    never reached inference)."""
    text = _ANSI.sub("", stdout)
    detections = [
        Detection(
            x=float(m["x"]), y=float(m["y"]), w=float(m["w"]), h=float(m["h"]),
            score=float(m["score"]), target=int(m["target"]),
        )
        for m in _DETECTION.finditer(text)
    ]
    t = _TIMING.search(text)
    if t is None:
        raise ValueError(f"no timing line in inference output:\n{text[:500]}")
    return InferenceResult(
        detections=detections,
        pre_ms=int(t["pre"]), infer_ms=int(t["infer"]), post_ms=int(t["post"]),
    )


# ---- reading a QR out of a photograph ---------------------------------------
#
# A photograph can be read instead of judged. A decoder on the device
# reports what it found in a captured frame, and comparing that against
# what the display was asked to show closes the loop: the payload only
# comes back if the panel rendered it, held it, and the camera was aimed
# and exposed well enough to resolve it.
#
# That is why this is a verdict and the frame's information density is
# not. A density figure says a frame has detail in it, which a photograph
# of the wrong screen, of a wall, or of the previous run's content all
# satisfy. The payload is generated fresh for each run, so a stale frame
# decodes to the previous run's payload and the comparison fails.

QR_RECORD_PREFIX = "QR_DECODE_"

QR_DECODED = "DECODED"
QR_NO_QR = "NO_QR"
QR_FILE_ERROR = "FILE_ERROR"
QR_STATUSES = (QR_DECODED, QR_NO_QR, QR_FILE_ERROR)

# The exit code each status must arrive with. The decoder reports its
# outcome twice, and these are checked against each other rather than one
# being trusted: a readable frame with no QR in it and a file that could
# not be read are different findings, and a reader that took either source
# alone would collapse them the first time they disagreed. That collapse
# is the whole defect this is built to refuse — a frame nobody could read
# must never arrive as a frame with nothing in it.
QR_EXIT_STATUS = {0: QR_DECODED, 2: QR_NO_QR, 3: QR_FILE_ERROR}

# The code the decoder exits with when it reached no outcome it could
# report. It shares no status with the three outcomes on purpose: those
# are findings about an image, and this says there is no finding — so
# folding it in with "nothing was found" would be the same collapse that
# the status-against-exit-code check exists to refuse, one level up.
#
# Deliberately not named for a particular cause. Being called wrongly is
# one route here and not the only one, and an error that volunteers a
# cause it cannot know sends the reader to the wrong place.
QR_EXIT_NO_OUTCOME = 1


# The payload is generated per run, and these two constants are the whole
# of what it may contain.
#
# Uppercase letters and digits only, which is narrower than the decoder's
# contract on purpose. A code carrying only these characters can be
# encoded in the denser of the two modes a QR encoder would choose for it,
# so the same number of characters costs fewer modules — and module size
# in the photograph is the measured difference between a code that reads
# and one that does not. Nothing here fixes a version or a module count:
# that is the encoder's to decide, and claiming a number for it from a
# character set would be a guess dressed as arithmetic.
#
# Short for the same reason. The payload only has to be unique across
# runs, and every character it gains is paid for in the capture.
QR_PAYLOAD_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
QR_PAYLOAD_LENGTH = 16

# The bytes the decoder will carry. Anything outside this range is dropped
# before it is counted, with the reason on stderr only — so a payload one
# character out of contract comes back as a count of zero and a status of
# NO_QR, which is byte for byte what an unlit display returns. That is why
# the charset is asserted where the payload is made.
QR_PAYLOAD_BYTE_MIN = 0x20
QR_PAYLOAD_BYTE_MAX = 0x7E


def qr_payload_refusal(payload: str) -> str | None:
    """Why this payload cannot be used as a per-run nonce, or None.

    Phrased as a refusal rather than a boolean so the reason travels with
    the verdict: the failure it prevents is indistinguishable from a dead
    display at the point it would otherwise be noticed, and by then the
    device is in hand.

    It refuses exactly what the decoder refuses, and nothing more. A
    stricter rule here would assert something about the decoder that is
    not true of it, which is worse than no rule: the next reader would
    take it as the contract.
    """
    if not payload:
        return "the payload is empty, so there is nothing to encode or compare."
    for position, character in enumerate(payload):
        point = ord(character)
        if point < QR_PAYLOAD_BYTE_MIN or point > QR_PAYLOAD_BYTE_MAX:
            return (
                f"character {position} of the payload is {character!r} "
                f"(0x{point:02x}), outside the 0x{QR_PAYLOAD_BYTE_MIN:02x}-"
                f"0x{QR_PAYLOAD_BYTE_MAX:02x} range the decoder carries. It "
                f"would be dropped before being counted, and the run would "
                f"report no symbol at all — the same answer an unlit display "
                f"gives, with the reason on stderr only."
            )
    return None


def new_qr_payload(
    length: int = QR_PAYLOAD_LENGTH, alphabet: str = QR_PAYLOAD_ALPHABET
) -> str:
    """A fresh payload for one run, refusing to return an unusable one.

    Fresh per run is what rules out a stale frame: a photograph left over
    from an earlier run decodes to that run's payload, and the comparison
    fails. Nothing about the image's age is examined, because nothing has
    to be.

    The alphabet is a parameter, so the assertion is on the result rather
    than on the constant: widening it is a one-word edit, and the point of
    checking here is that such an edit cannot reach a device. A generator
    that trusted its own default would be checking the one thing that
    cannot change.
    """
    payload = "".join(secrets.choice(alphabet) for _ in range(length))
    refusal = qr_payload_refusal(payload)
    if refusal is not None:
        raise ValueError(f"generated an unusable payload: {refusal}")
    return payload


@dataclass(frozen=True)
class QRCode:
    """One symbol the decoder read out of the image.

    ``payload_len`` is the decoder's own count of the payload's bytes, and
    it is carried rather than derived because the decoder's payload buffer
    is fixed-size and its contents past that length are not meaningful.
    Holding both means a payload that arrives short can be seen, instead
    of being compared against the expectation as though it were whole.
    """

    payload_len: int
    payload: bytes


@dataclass(frozen=True)
class QRDecode:
    """Everything the decoder said about one image."""

    path: str
    status: str
    codes: tuple[QRCode, ...]

    @property
    def decoded(self) -> bool:
        return self.status == QR_DECODED


def parse_qr_decode(stdout: str, exit_code: int) -> QRDecode:
    """Parse the decoder's records, or raise.

    Both halves of the decoder's report are required, because it states
    its outcome twice — once as an exit code and once as a status line —
    and the contract is that either is sufficient on its own. Given both,
    the useful thing to do with the redundancy is to check it: if they
    disagree, neither is trustworthy and there is nothing to choose
    between them.

    Records are read in the order they were printed rather than gathered
    by pattern. The order carries meaning that a set does not: the
    lengths and payloads interleave one pair per symbol, and the status
    comes last so that a report cut short in transit cannot look
    complete.
    """
    stdout = without_password_prompt(stdout)

    if exit_code == QR_EXIT_NO_OUTCOME:
        raise ValueError(
            f"the decoder exited {QR_EXIT_NO_OUTCOME}, which means it "
            f"reached no outcome it could report — so there is nothing here "
            f"about the image, and in particular this is not 'no symbol was "
            f"found'. Read its stderr for the reason; this exit code does "
            f"not carry one.\n{stdout[:500]}"
        )
    expected_status = QR_EXIT_STATUS.get(exit_code)
    if expected_status is None:
        codes = ", ".join(str(c) for c in sorted(QR_EXIT_STATUS))
        raise ValueError(
            f"the decoder exited {exit_code}, which is not one of its "
            f"documented codes ({codes}, or {QR_EXIT_NO_OUTCOME} for no "
            f"outcome). Treating an unknown code as any of them would be a "
            f"guess about what happened.\n{stdout[:500]}"
        )

    lines = stdout.split("\n")
    path: str | None = None
    count: int | None = None
    status: str | None = None
    codes_read: list[QRCode] = []
    pending_len: int | None = None
    status_line: int | None = None

    for number, line in enumerate(lines):
        if not line.startswith(QR_RECORD_PREFIX):
            continue
        # A line claiming to be a record and failing to parse is an error,
        # never a line to skip. Skipping is what turns a truncated report
        # into a shorter, apparently healthy one.
        keyword, _, value = line.partition(" ")

        if keyword == "QR_DECODE_FILE":
            if path is not None:
                raise ValueError(f"two QR_DECODE_FILE records: {path!r} and {value!r}")
            if not value or value.split() != [value]:
                raise ValueError(
                    f"QR_DECODE_FILE carries {value!r}, which is empty or holds "
                    f"whitespace; the path is echoed back as it was given and "
                    f"this example passes paths that have neither"
                )
            path = value

        elif keyword == "QR_DECODE_COUNT":
            if count is not None:
                raise ValueError(f"two QR_DECODE_COUNT records: {count} and {value!r}")
            if not value.isdigit():
                raise ValueError(f"QR_DECODE_COUNT is not a count: {value!r}")
            count = int(value)

        elif keyword == "QR_DECODE_PAYLOAD_LEN":
            if pending_len is not None:
                raise ValueError(
                    f"QR_DECODE_PAYLOAD_LEN {value!r} follows another length "
                    f"({pending_len}) with no payload between them, so one "
                    f"symbol's payload is missing"
                )
            if not value.isdigit():
                raise ValueError(f"QR_DECODE_PAYLOAD_LEN is not a length: {value!r}")
            pending_len = int(value)

        elif keyword == "QR_DECODE_PAYLOAD":
            if pending_len is None:
                raise ValueError(
                    f"QR_DECODE_PAYLOAD {value!r} arrived with no length before "
                    f"it. The length is what makes the payload readable, so a "
                    f"payload without one cannot be compared against anything"
                )
            payload = value.encode("utf-8", errors="surrogateescape")
            if len(payload) != pending_len:
                raise ValueError(
                    f"QR_DECODE_PAYLOAD carries {len(payload)} bytes against a "
                    f"declared length of {pending_len}. The payload arrived "
                    f"short or long: either it was truncated in transit, or the "
                    f"line ending was counted as payload. Comparing it against "
                    f"the expected payload now would report a mismatch and "
                    f"blame the display."
                )
            codes_read.append(QRCode(payload_len=pending_len, payload=payload))
            pending_len = None

        elif keyword == "QR_DECODE_STATUS":
            if status is not None:
                raise ValueError(f"two QR_DECODE_STATUS records: {status!r} and {value!r}")
            if value not in QR_STATUSES:
                raise ValueError(
                    f"unknown decoder status {value!r}; expected one of "
                    f"{', '.join(QR_STATUSES)}"
                )
            status = value
            status_line = number

        else:
            raise ValueError(
                f"unknown record {keyword!r} in the decoder's output. A record "
                f"this example does not know is a contract that changed, and "
                f"guessing at it is how a changed format goes unnoticed: "
                f"{line!r}"
            )

    if pending_len is not None:
        raise ValueError(
            f"the output ends with a declared payload length ({pending_len}) "
            f"and no payload, so the last symbol's payload is missing"
        )
    if status is None:
        raise ValueError(
            f"no QR_DECODE_STATUS record, so the decoder's outcome is unknown. "
            f"It is the last line of every report, which is what makes its "
            f"absence evidence that the output was cut short rather than that "
            f"the decoder said nothing.\n{stdout[:500]}"
        )
    if path is None:
        raise ValueError(f"no QR_DECODE_FILE record:\n{stdout[:500]}")
    if count is None:
        raise ValueError(f"no QR_DECODE_COUNT record:\n{stdout[:500]}")

    trailing = [line for line in lines[status_line + 1 :] if line.strip()]
    if trailing:
        raise ValueError(
            f"the status is not the last line; {len(trailing)} line(s) follow "
            f"it, beginning {trailing[0]!r}. The status comes last so that a "
            f"report cut short cannot read as a complete one, and output after "
            f"it means this is not the whole report, or not only this report"
        )

    if len(codes_read) != count:
        raise ValueError(
            f"the decoder reports {count} symbol(s) and printed "
            f"{len(codes_read)} payload(s). One of the two is wrong and the "
            f"count is not the one to trust: a missing payload is the shape "
            f"this would otherwise hide"
        )
    if status == QR_DECODED and count == 0:
        raise ValueError(
            f"status {QR_DECODED} with a count of 0, which says a symbol was "
            f"both read and not read"
        )
    if status in (QR_NO_QR, QR_FILE_ERROR) and count != 0:
        raise ValueError(
            f"status {status} with a count of {count}; neither outcome has a "
            f"symbol to report"
        )
    if status != expected_status:
        raise ValueError(
            f"the decoder exited {exit_code}, which is {expected_status}, and "
            f"reported status {status}. The two are meant to be independently "
            f"sufficient, so a disagreement makes both unusable — in "
            f"particular a frame that could not be read must never arrive as "
            f"a frame with nothing in it"
        )

    return QRDecode(path=path, status=status, codes=tuple(codes_read))


def round_trip_refusal(expected: str, decode: QRDecode) -> str | None:
    """Why this decode is not the displayed payload coming back, or None.

    This is the verdict the demo rests on, and it is a comparison of
    bytes rather than of text: the decoder states its own length for each
    payload and the reader has already held it to that, so what is
    compared here is exactly as many bytes as the decoder said it read.
    A text comparison would be the same answer most of the time and a
    different one precisely when something has gone wrong with the
    length, which is the case worth catching.

    The expected payload is checked before the comparison. If it is not
    one the decoder could have carried, that is the finding — reporting a
    mismatch instead would send the reader to look at the panel for a
    fault that is in the payload we generated.

    One symbol, not at least one. The run puts a single code in front of
    the lens, so a second one means the frame held something the demo did
    not put there, and a rule that accepted any matching code would pass
    that silently.
    """
    refusal = qr_payload_refusal(expected)
    if refusal is not None:
        return (
            f"the payload this run meant to display is not one the decoder "
            f"could carry, so nothing can be concluded about the frame: "
            f"{refusal}"
        )

    if not decode.decoded:
        return (
            f"the decoder reported {decode.status} for {decode.path}, so no "
            f"payload came back to compare. {decode.status} does not say why: "
            f"a code too small or too blurred to resolve and a display with "
            f"nothing on it give the same status and the same exit code, and "
            f"the reason is on the decoder's stderr only — read the "
            f"diagnostics recorded beside this run's records."
        )

    if len(decode.codes) != 1:
        found = ", ".join(repr(c.payload) for c in decode.codes)
        return (
            f"the frame held {len(decode.codes)} symbols, not one: {found}. "
            f"The run displays a single code, so a second one is something "
            f"the demo did not put in front of the lens."
        )

    got = decode.codes[0].payload
    want = expected.encode("ascii")
    if got != want:
        return (
            f"the payload read out of the photograph is {got!r} "
            f"({decode.codes[0].payload_len} bytes), not the {want!r} this "
            f"step displayed. A decode that works and disagrees is a "
            f"photograph of content displayed earlier — the previous code "
            f"in this same session, or a frame left from an earlier run — "
            f"because a stale frame reads as whatever it was taken of."
        )

    return None


def frame_payload_refusal(decodes) -> str | None:
    """Why two photographs have not established one payload, or None.

    The frame carries no expectation to compare against, and that is
    deliberate. It displays a code whose payload is not published
    anywhere trustworthy, so an expectation written here would be a
    guess, and a run that disagreed with it could not be told from a run
    that read the screen correctly.

    What replaces the expectation is agreement. The symbol carries its
    own error correction, so a decoder does not return a payload it has
    not checked against the symbol's own codewords — a successful read
    is self-validating. Two independent reads of the same screen that
    return the same bytes have therefore established what was displayed,
    without anyone having to know it in advance.

    Two are required rather than one because a single read establishes
    the payload and nothing about whether the rig is steady. Two that
    agree also rule out a frame that happened to resolve once.
    """
    if len(decodes) < 2:
        return (
            f"only {len(decodes)} photograph(s) reached the decoder, and one "
            f"reading establishes a payload without establishing that the "
            f"rig can produce it twice."
        )

    payloads = []
    for position, decode in enumerate(decodes):
        if decode is None:
            return (
                f"photograph {position} never reached the decoder, so there "
                f"is nothing from it to agree with."
            )
        if not decode.decoded:
            return (
                f"photograph {position} returned {decode.status}, so no "
                f"payload came out of it. The decoder's diagnostics are the "
                f"only thing that separates a code it could not read from a "
                f"screen with nothing on it."
            )
        if len(decode.codes) != 1:
            return (
                f"photograph {position} held {len(decode.codes)} symbols, "
                f"not one, so which of them was displayed is undecided."
            )
        payloads.append(decode.codes[0].payload)

    first = payloads[0]
    for position, payload in enumerate(payloads[1:], start=1):
        if payload != first:
            return (
                f"the readings disagree: photograph 0 returned {first!r} and "
                f"photograph {position} returned {payload!r}. Both are "
                f"self-validating against the symbol's own error correction, "
                f"so two different answers mean two different screens were "
                f"photographed, not one screen read two ways."
            )

    return None


# What a failing run is attributable to. Three outcomes, because "the demo
# went red" covers cases that establish entirely different things, and
# only one of them is evidence about the decode.
#
# The demo is also run deliberately against a display showing nothing, to
# show that it fails. That run is only worth anything if the failure comes
# from the comparison: a run that stops at the display check has shown
# that the display check works, which was never in doubt.
RED_FROM_PAYLOAD = "payload-comparison"
RED_FROM_DISPLAY_CHECK = "display-check"
RED_NOT_PERFORMED = "not-performed"
# A fourth, reached before anything is displayed: the address no longer
# serves the bytes the margin was measured from. It is not an outcome of
# a run — it is a refusal to spend one, and it is attributed like the
# others so the reason travels with it rather than being left to whoever
# reads the failure.
RED_FROM_DISPLAYED_ARTIFACT = "displayed-artifact"
NO_RED = "none"


@dataclass(frozen=True)
class RedAttribution:
    """Which part of a run produced its result, and what that is worth."""

    source: str
    reason: str

    @property
    def discriminated(self) -> bool:
        """Whether the comparison is what produced the red.

        The one outcome that says anything about the decode. Everything
        else is a run that stopped earlier, and a run that stopped
        earlier is not a weaker version of this — it is silent.
        """
        return self.source == RED_FROM_PAYLOAD


# What the gate holds before the first stage has reported anything. It is
# a failure reason rather than an absence, because the two states that
# matter here are "passed" and "everything else", and a stage that died
# before it could judge anything belongs in the second.
STAGE_ONE_NOT_RUN = "it did not run, or it ended before it judged anything"


def stage_two_skip_reason(stage_one_failure: str | None) -> str | None:
    """Why the second stage must not run, or None if it may.

    The second stage tests one thing, and it can only test that thing if
    the first stage established that the picture reaches the camera at
    all. Run without it, a pass says nothing: a result over a photograph
    nobody has shown to contain the subject is not evidence about the
    detector, however green it is.

    That direction is the one worth guarding. A failure after an
    unproven path is merely uninformative, and the reader can see it is
    red. A *pass* after an unproven path looks exactly like a working
    system, and the only run that has ever been published from this
    example was one of those — it reported three candidates and a top
    score over a featureless frame.

    The reason travels with the refusal rather than being left to the
    reader, because a bare skip is an absent result wearing a label: it
    cannot be told from a stage nobody wrote.
    """
    if stage_one_failure is None:
        return None
    return (
        f"the first stage did not pass, so nothing measured here could be "
        f"attributed to the detector rather than to the picture: "
        f"{stage_one_failure}"
    )


def attribute_red(
    showing_requested_source: bool,
    decode: QRDecode | None,
    round_trip: str | None,
) -> RedAttribution:
    """Attribute a run's outcome before anyone reads it as a verdict.

    Written because the alternative is a person deciding it from
    scrollback with a device in hand, at the one moment the answer is
    expensive. The three outcomes are separable here only because the
    decode command keeps its diagnostics apart from its records; from a
    status and an exit code alone they are not.

    ``showing_requested_source`` is both halves of the display's reported
    state together, deliberately. A display reports that it is showing
    something whatever is on it, including content from before this run,
    so the state alone does not distinguish a honoured request — and a
    run that proceeds on it is one photograph away from a verdict about
    the wrong screen.
    """
    if not showing_requested_source:
        return RedAttribution(
            RED_FROM_DISPLAY_CHECK,
            "the run stopped at the display check, before anything was "
            "photographed. That shows the check works and says nothing "
            "whatever about the decode — in particular it is not evidence "
            "that a code could or could not be read.",
        )

    if decode is None:
        return RedAttribution(
            RED_NOT_PERFORMED,
            "no capture reached the decoder, so the run was not performed "
            "rather than failed. A short window, a display left on earlier "
            "content, a first request that was dropped, or a capture that "
            "never arrived all land here, and none of them is a finding "
            "about the camera or the decoder.",
        )

    if round_trip is None:
        return RedAttribution(
            NO_RED,
            "the payload displayed came back out of the photograph, so "
            "there is no red to attribute.",
        )

    return RedAttribution(
        RED_FROM_PAYLOAD,
        f"the decoder ran on a photograph and the comparison refused it, "
        f"so the red is the comparison discriminating: {round_trip}",
    )
