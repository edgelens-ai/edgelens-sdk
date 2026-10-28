# End-to-end demo — face detection on a real reCamera

One pytest test that rents a real camera, puts an image on the device's
display so there is something to look at, photographs that display with
the camera, runs a face detector over the photograph, brings the image
back, and hands the camera back.

That loop is the whole point of the arrangement: **the platform puts an
image on your device's display, your camera photographs it, and your
model detects against what it saw.** Every device you rent has a screen
facing its lens, so a test can provide its own subject and get the same
scene on every run — no rig to build, nothing to hold up to a camera.

## What the demo shows

`tests/test_demo_end_to_end.py::test_demo_face_detection` runs against a
real reCamera running reCamaginedOS:

1. The `device` fixture from `pytest-edgelens` creates a session and waits
   until it is ready.
2. `device.deploy` sends a capture utility, the face model and an
   inference binary to the camera.
3. `device.display.show` puts a face image on the device's display, and
   the test confirms the display reports that image before continuing.
4. `device.exec` clears every path a capture run writes and confirms they
   are gone.
5. `device.exec` captures a short burst of frames from the camera's
   sensor — photographs of the display from step 3 — and the camera
   reports the frame number, elapsed time and encoded size of each.
6. `device.exec` runs the face detector over the last frame of the burst,
   which writes an annotated copy.
7. The test fetches a few of the captured frames and the annotated image
   back, checks each against the camera's own digest, and saves them,
   along with the burst's records, into a directory of its own under
   `artifacts/` — `artifacts/run-<when the run started>/`. The run prints
   that path before it does anything else, so you never have to work it
   out. Each run gets its own, and no run deletes or overwrites another's.
8. The plugin releases the session in teardown.

The payload is in `models/`. The command building and parsing live in
`tests/demo_inference.py`.

### Why step 3 checks what the display reports

`show()` has no return value, so the only way to know the request took
effect is to ask the display what it is showing — and to look at both
halves of the answer:

- `state` must be `showing`. On its own this is weak: a display showing
  *anything at all* reports `showing`, including content that was up
  before your test ran.
- `source` must be the URL you asked for. That is what distinguishes
  your image from whatever was there before.

Neither check tells you the image is lit up on the panel. The display
reports the source it accepted; whether a frame of that source actually
decoded is a separate question, and not every deployment answers it yet.
So a source that turns out to be unreachable, or that arrives in a form
the display cannot play, can still be reported as `showing` — and the
camera would photograph a blank screen.

The blank-frame check below is what covers that gap, and it is why that
check is an assertion rather than advice. Make these two anyway: a
photograph of the *wrong* screen satisfies every other assertion in the
file, and `source` is the only thing that rules it out.

### What it asserts, and what it deliberately does not

It asserts that the display reported the image this test asked for, that
frames were captured from the sensor during the session, that the burst
is internally consistent and every frame it reported is accounted for,
and that the annotated image came back intact.

**It does assert that the annotated frame is not blank.** A photograph of
an unlit screen passes every other check in the file — it is a real
image, from this run, with a digest matching the camera's own — and it is
worthless. So the test measures how much information the returned frame
carries, in bits of compressed JPEG per pixel, and fails below a
threshold. A flat field compresses to almost nothing; scene detail does
not.

**It does not apply that threshold to the captured frames.** The
threshold was measured at the size the annotated frame comes back at, and
the measure is per-pixel, so the same picture scores lower the larger it
is. The captured frames are larger, and a perfectly good one scores below
the threshold — applying it there would report a working camera as blank.
Their sizes are printed instead, and the sizes are what the burst is for:
a near-empty frame compresses to a fraction of a detailed one, so sizes
rising across the burst is the camera coming up to exposure. If they never
rise, the run says so in as many words.

**It does not assert what is in the picture.** Even with a known image on
the display, what the camera records depends on the physical setup —
focus, angle, glare, how much of the frame the screen fills — so the
detections are printed as information. Asserting on them would be
testing the scene rather than the service. Model accuracy is covered
separately by `models/sample_faces.jpg` and the offline tests in
`tests/test_demo_parsing.py`.

Those two are not in tension. Whether there is *any* detail in the frame
is a property of the image and is measurable. Whether the right thing is
in it is a judgement about the world. So the run refuses a picture of
nothing by itself, and a person only needs to look when there is
something to look at — the saved image in your run's own directory under
`artifacts/` is where, and the run prints that path when it starts.

### Why the burst is one run, not several

A camera needs a short time after starting before it is exposing
correctly, and a frame grabbed before then is dark whatever is in front
of the lens. Starting the camera again restarts that settling, so taking
frames in separate runs would measure the same first moment over and
over. One run, several frames, is what shows the progression.

How many frames and at what spacing is the capture utility's own
decision. It reports the schedule it used, and this example keeps no copy
of it — a value held in two places is one that can disagree with itself.

### Why step 4 exists

The capture utility creates each output file only once a frame has
actually arrived. Every failure route therefore leaves whatever was
already at that path in place, with a correct exit code. Without proving
the paths are empty first, a failed capture on a second run would present
the *previous* run's photographs — real images of the right scene — as
fresh ones.

The burst is cleared by pattern rather than by name, because its length
is not known in advance. Clearing only the final frame's own name would
leave an earlier run's burst behind, and those files pass every later
check: their sizes agree with their records and their digests match. They
are simply from a different run.

### The images come back through `exec`

There is no download API, so each image is base64-encoded on the camera
and decoded locally. `exec` output is capped at 256 KiB and base64
inflates 4/3, so files are fetched in ranges and the reassembled bytes
are compared against the digest the camera reported.

That makes every image a number of round-trips, which is why only a few
come back: the first frame, the final one, and the pair either side of any
sharp rise in size. The rest stay on the camera — their numbers are
already in the records, and the records are the measurement. Each one is
listed with the reason it was not fetched, so a frame left behind on
purpose is never confused with one that went missing.

Two independent counts guard the transfer. The camera reports what it
wrote; the files are then measured on the camera by something else, which
catches a write that stopped early even for the frames that never come
back; and the bytes that arrive are hashed locally against the camera's
own digest. Three different things measured by three different means — if
any two were merged, the check they form together would stop working.

Saved images and records are gitignored: they are photographs of whatever
the rented device could see.

## Prerequisites

- An EdgeLens account and an API key scoped to reCamaginedOS on reCamera
  devices (customer portal → `/app/keys` → Create).
- Python ≥ 3.9.
- The container image from [README § Setup](README.md#setup), built once:

  ```bash
  cd examples/pytest
  make -C ../.. image
  ```

- A `.env` created from `.env.example`, with your key in it:

  ```bash
  cp .env.example .env
  # edit .env — EDGELENS_API_KEY=el_live_…, and uncomment and set EDGELENS_BASE_URL if self-hosting
  ```

`.env` is passed to the container as a file, so there is nothing to
source: the key never reaches a command line, where it would be visible
to anything that can read the process table.

or export the key directly:

```bash
export EDGELENS_API_KEY=el_live_…
```

## Run

```bash
make demo
```

That runs the demo in the container, passing `.env` to it and mounting
this directory so the run can write its artifacts where you can read
them back. It works from any directory:

```bash
make -C examples/pytest demo
```

`make -C examples/pytest test` runs the offline tests, which need neither
a device nor an API key.

- `--edgelens-os=recamagined` is required. The test is marked for
  reCamaginedOS, and the plugin skips it under the default OS tier.
- `-s` shows the test's `[demo]` result line as it runs.
- For a self-hosted or dev deployment, add
  `--edgelens-base-url=https://<your-api-host>`, or set
  `EDGELENS_BASE_URL`. The precedence is in [README § Run](README.md#run).
- The base URL must be `https://` with a hostname. The SDK's URL
  validator rejects plain `http://` and private IPs.

## Expected output

The first thing the run prints is where it is going to write, on a line
beginning `[demo] this run writes to` — that is your run's own directory
under `artifacts/`, and reading it off the output is the way to find your
images. You do not have to work out the naming.

After that it prints a progress line as it goes and ends with a summary:
the sensor capture and which scheduled frame settled, the frame-by-frame
account, the images brought back, the annotated frame with its size and
digest, the detection candidates, the displayed image and final display
state, and the pre / infer / post timings.

No transcript of a real run is reproduced here. None was saved from the
run the figures below come from, and a block formatted to look like
captured output gets read as captured output. Run it and read your own.

A full run typically takes about 10–12 minutes. Most of that is preparing
a fresh device before the session is ready.

### Figures from one run, 2026-10-06

| Quantity | Observed | Source |
|---|---|---|
| Total wall clock | about 11 minutes (`1 passed in 669.61s`) | that run's pytest summary line; no stdout was saved, so there is no file for this one |
| Capture to returned image | about 4.2 seconds (the settled frame, at 4,211 ms) | `demo5-capture-accounting.txt`, settled row |
| The returned image | 1920x1080, 185,494 bytes | `demo5-capture.jpg`, cross-checked against the same settled row |
| Sensor warm-up, which is **not** the time to an image | the first frame off the sensor, at 1,211 ms, is not usable; the next one, 33 ms later, is | `demo5-capture-accounting.txt`, frame rows |

**The files named above are the artifacts of one recorded run on our own
bench, and they are not shipped with this package.** Your own run writes
files of the same names into its own directory under `artifacts/`, which
starts out with nothing in it. The names above are given so you can see
which measurement each number came from, not so you can open them here.

One run's numbers, not a specification. Your own will differ with the
device, the network and what the sensor is pointed at.

The image you get back is the settled frame, so **about 4.2 seconds is
the figure that describes waiting for a picture.** The warm-up row is a
fact about the sensor and not about delivery — nothing is returned at
1.2 seconds, and reading it as a time-to-image would understate the wait
by a factor of about 3.5.

Both timing figures are observations, not settings to copy. The two
warm-up frames are one frame interval apart, so what that row records is
simply that the first frame off the sensor is not usable and the next one
is. The rule that follows has no number in it: **discard the first
frame.** Waiting a fixed 1.2 seconds is not the lesson, and neither is
waiting 4.2.

## Offline check

No hardware or API key needed:

```bash
# Parser unit tests: pass without a device, with the network off.
make test

# The device tests are collected without being run, so nothing is allocated.
make demo PYTEST_ARGS=--collect-only
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `AuthenticationError: Invalid or expired API key` on every call | API key revoked, mistyped, or for the wrong environment | Mint a fresh key in the portal and reload `.env` into the environment |
| `AuthenticationError: API key does not have permission: …` | The key isn't permitted to request this device type or OS (for the demo, `recamera-2002` / `recamagined`), or the requested session is longer than the key allows | Use a key scoped for that device type and OS; contact EdgeLens support to get one |
| Session never becomes ready | No device matching the session's device type and OS was available, e.g. all are in use | Retry later; if it keeps happening, contact EdgeLens support with the session id |
| `device.deploy` or `device.exec` fails | Wrong model or binary path, or the binary isn't executable | Check the paths in `tests/demo_inference.py`. Deployed files arrive without the executable bit: the test runs `chmod +x` on the binary before invoking it, so a custom binary needs the same |
| Capture exits 1 having printed missing shared libraries | The runtime library path was not passed on the command itself | The image has no default search path for these libraries and a non-interactive command does not read the shell profile, so the path must be set on the command. See `models/README.md` |
| Capture exits 1 with no library errors | Video setup failed, or no frame arrived within 10 s | Report it: the capture utility could not use the sensor. This is distinct from a missing-library failure, which is a packaging problem rather than a capture one |
| Preflight fails: path still present after removal | Something else holds an output path, or the directory is not writable | Do not run the capture — the assertion exists precisely so a stale image cannot be mistaken for a new one |
| Preflight fails: the burst pattern was not proved empty | An earlier run's frames are still on the device and could not be removed | Do not run the capture. Those frames would be reported by this run and would pass every check afterwards, because they are real images with matching sizes and digests — the difference is only visible here |
| Capture reports `INCOMPLETE_NO_FRAMES` | The camera produced nothing at all within its timeout | Report it with the saved records: this is a camera or startup problem, not a timing one, and it is distinct from frames arriving and never settling |
| Capture reports `INCOMPLETE_NOT_SETTLED` | Frames arrived, but the run ended before the last scheduled one | Report it with the saved records. The frames that did arrive are kept and fetched, and their sizes show how far the camera had got |
| A frame's reported size does not match the file on the device | The write stopped early | Report it with the saved records. This is why the two counts are taken separately; one number alone could not show it |
| The run says the sizes never rose across the burst | Nothing in the burst carries more detail than the frame taken immediately | Compare the first and final saved images by eye. Either the camera is not seeing the subject, or there is nothing in front of it to see — the images distinguish those and the numbers do not |
| Fetched image digest does not match the camera's | The output was truncated in transit | Lower the fetch chunk size in `tests/demo_inference.py`; the cap is on a single `exec` response |
| Test skipped: `requires --edgelens-os=recamagined` | Run without the OS flag | Add `--edgelens-os=recamagined` |
| `httpx.ConnectError: Name or service not known` | Base URL missing | See the matching row in [README § Troubleshooting](README.md#troubleshooting) |
