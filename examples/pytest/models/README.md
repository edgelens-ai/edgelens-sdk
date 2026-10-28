# Reference capture + model + inference binary for the demo pytest

Most of these files are the customer's demo payload — deployed to a running recamagined session via `device.deploy` (they land in `/userdata/Models/`), then run via `device.exec`. Nothing here is part of the SDK itself. `qr_decode` is the exception, and it is stated here rather than left to be inferred from the list: it is committed and ready to deploy, and nothing in the demo deploys it or runs it yet.

The demo is a two-stage pipeline: `capture_jpeg` takes a frame from the camera's sensor, then `sscma-model` runs the face detector over that frame and writes an annotated copy, which the test fetches back. `sample_faces.jpg` is no longer what the demo runs on — it is kept for the offline parser tests and for a model-correctness check.

## Contents

| File | Purpose | Source | License |
|---|---|---|---|
| `sscma-model` | Standalone inference CLI, RISC-V 64 musl. Loads a `.cvimodel`, runs one pass on an input image, prints results to stdout. | Built from `solutions/sscma-model/` against Seeed Studio's SSCMA-Micro; committed unmodified, see Provenance below. | Apache-2.0 |
| `scrfd_500m_kps_int8.cvimodel` | SCRFD 500m face detection, int8-quantized for CV181X (SG2002). ~766 KB. | `Seeed-Studio/sscma-example-sg200x` `models/face/`. | Model weights per Seeed's redistribution terms |
| `capture_jpeg` | Sensor capture, RISC-V 64 musl. Writes a short burst of JPEGs off the encoder in one run and reports each one on stdout. | Built from `solutions/capture_jpeg/`; committed unmodified, see Provenance below. | Apache-2.0 |
| `sample_faces.jpg` | Test image (the "Zidane" photo from the reference set). Input for the offline parser tests and the model-correctness check — **not** what the demo runs on. | Same repo, `images/zidane.jpg`. | See upstream repo |
| `qr_decode` | Reads QR codes out of a captured JPEG, RISC-V 64 musl. Takes one image path, reports each symbol's payload and its own outcome on stdout, diagnostics on stderr. Deployed with the rest of the payload; no run executes it yet. | Built from `solutions/qr_decode/`; committed unmodified, see Provenance below. | Apache-2.0, and ISC for the statically-linked quirc — see Provenance |

### Provenance of the committed `qr_decode`

Committed **unmodified** as built elsewhere — not built, stripped or edited in this repository.

| | |
|---|---|
| sha256 | `583c9a8c1604e71ac0bd38ba6fb787598a6da57a86f93a9603213d0447413496` |
| size | 67896 bytes |

It statically links [quirc](https://github.com/dlbeer/quirc) for the decoding itself, which is ISC-licensed and carries an attribution condition that a binary distribution does not satisfy on its own:

> Copyright (C) 2010-2012 Daniel Beer <dlbeer@gmail.com>
>
> Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is hereby granted, provided that the above copyright notice and this permission notice appear in all copies.
>
> THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

The notice is reproduced here because the binary is stripped and carries it nowhere else.

It is stripped, carries no `RPATH` and no `RUNPATH`, and the only absolute path in it is the musl interpreter. It links OpenCV's `core`, `imgcodecs` and `imgproc` alongside `libstdc++`, `libgcc_s` and `libc`, so it needs the same explicit library search path the two binaries above do, for the same reason: the image ships no `/etc/ld-musl-*.path` and `ssh host '<command>'` never runs `/etc/profile`.

**If this file is ever replaced, sweep the replacement before committing it** — the absolute-path enumeration under §Provenance of the committed `capture_jpeg` is the recipe, and the rule that goes with it applies here too: account for every entry it returns rather than filtering any of them out.

## The image shown on the display

The demo gives the camera a subject by putting an image on the device's
display, so this one is **not** a file in this directory — the device
fetches it over the network itself, which means it has to be reachable
from wherever the device is and from wherever you are.

| | |
|---|---|
| URL | `https://upload.wikimedia.org/wikipedia/commons/d/d3/Albert_Einstein_Head.jpg` |
| Subject | One large, frontal, high-contrast face — the easy case for a detector photographed off a screen |
| Source | Wikimedia Commons |
| License | The Commons file page states public domain (United States). Re-check the page before relying on it; a Commons licence tag can change, and this is the published claim rather than one made here |
| Defined in | `tests/demo_inference.py` (`DISPLAY_IMAGE_URL`) |

Why these constraints, if you swap it for your own: it must be `https`,
stable rather than a rotating hotlink, openly licensed with the licence
named, fetchable without a token, and not on a host behind your own
network — the fetch happens from the device side, so anything only you
can reach will fail there. `tests/test_demo_parsing.py` checks the first
and last of those offline.

## The code shown on the display

The other image the display carries is a QR code, so the demo can read
back out of the photograph the thing it put on the screen. The code is
generated for this project and committed at
`fixtures/edgelens-www-qr.png`; the device fetches it over the network
like the one above, from the address this repository publishes that file
at. The committed copy is the source, and the margin around the symbol is
the property that decides whether it can be decoded at all, so the
measurement is re-takeable from the repository rather than from a
download.

| | |
|---|---|
| URL | `https://raw.githubusercontent.com/edgelens-ai/edgelens-sdk/main/examples/pytest/fixtures/edgelens-www-qr.png` |
| Committed copy | `fixtures/edgelens-www-qr.png`, 921 bytes, sha256 `ab4ae0a3e612019d28edadbea7615ec8cfe6f5c53221b2519aac148fca9d7912` |
| Payload | `https://www.edgelens.ai`, and nothing else |
| Geometry | 957x957, square, 1-bit greyscale; version 2, error correction M, 25-module symbol at 29 px per module; four modules of white on every side |
| Generated with | `segno` (listed in `requirements.txt`), with the encoder's default four-module border |
| Measured by | `tests/test_demo_parsing.py`, with the instrument in `tests/qr_quiet_zone.py` |
| Defined in | `tests/demo_inference.py` (`FEASIBILITY_QR`) |

The margin is in the file itself: the code is written with the encoder's
quiet zone and committed as that raster, so what is displayed carries the
margin it was measured with. The address only serves the file once this
repository is public, and the file behind it can be replaced without the
address changing, which is why the committed copy is pinned by digest and
the digest is what the measurement is attached to.

Four modules is the symbol's own requirement and it is also the most a
code found on the web will have, because it is what every encoder emits
unless its author changed the setting: the symbol then occupies M/(M+8)
of the image whatever version it is. There is no headroom in it for a
display that does not show the whole image or a camera that does not
frame the whole display.

## Binary details

```
$ file sscma-model
sscma-model: ELF 64-bit LSB executable, UCB RISC-V, version 1 (SYSV),
             dynamically linked, interpreter /lib/ld-musl-riscv64v0p7_xthead.so.1,
             stripped
```

Interpreter `ld-musl-riscv64v0p7_xthead.so.1` matches the recamagined whole-disk image (musl, XuanTie C906 RISC-V core). Dynamically linked against the CV181X TPU SDK libs that the whole-disk image ships in `/usr/lib` and `/mnt/system/lib`, and against `libmosquitto.so.1` and `libcares.so.2` from the device OS.

## Invocation on the camera

```sh
./capture_jpeg [output-path] [frame-schedule]                 # default /userdata/local/capture.jpg
./sscma-model <model_file> <input_image> [<output_image>]
```

`capture_jpeg` takes a short burst of frames in one run rather than a single frame, because a camera needs a moment after starting before it is exposing correctly and a frame grabbed before then is dark whatever is in front of it. Starting the camera again restarts that settling, so the burst has to come from one invocation to show a progression at all.

With an output path of `capture.jpg` it writes `capture.jpg` — the last scheduled frame, which is what inference runs on — plus `capture.f000.jpg`, `capture.f001.jpg` … one per scheduled index, and `capture.manifest.txt`. It reports each file it wrote on stdout with the frame number, the elapsed time since the camera started, and the encoded size; the schedule it used is reported too, so nothing needs to know it in advance. Those sizes are the measurement: a near-empty frame compresses to a fraction of a detailed one, so sizes rising across the burst is the camera coming up to exposure.

It exits 0 only when the whole scheduled burst was captured and the settled frame written. On any other outcome it exits non-zero, the settled path is guaranteed absent, and the burst and manifest are deliberately **kept** — a camera that never settles produces the most informative artifact a run can return, so the failure route preserves it. The status distinguishes no frame arriving at all from frames arriving without settling; those are different faults and only one of them is about exposure.

**`capture_jpeg` writes each output file only once a frame has arrived.** So every failure route leaves whatever was already at that path untouched, and a short write leaves a partial file — with a correct exit code in both cases. Delete the output paths and confirm they are gone before each attempt, or a previous run's images read as a fresh capture. **Clear the burst by pattern (`capture.f*.jpg`) and not by name:** how many frames a run writes is the binary's own decision, so clearing only the final frame's name leaves an earlier, longer run's frames in place — and those pass every later check, because they are real images whose sizes and digests agree. The demo does both in its preflight step.

`capture_jpeg` has no resolution option: it takes 1920x1080 off encoder channel 1. Changing that needs a rebuilt binary.

### Provenance of the committed `capture_jpeg`

Committed **unmodified** as built elsewhere — not built, stripped or edited in this repository.

| | |
|---|---|
| sha256 | `1848c1e1ea4590b026fc81d88e700f048afa3d9cec177859f3236bd79f0ccdb8` |
| size | 56520 bytes |

It is stripped, carries no `RPATH` and no `RUNPATH`, and the only absolute paths in it are the musl interpreter, `/mnt/cfg/param/`, its own default output path, and three `/sys/module/cvi_vc_driver/parameters/*` entries the vendor SDK writes at runtime. **If this file is ever replaced, sweep the replacement before committing it**, because a build can carry the absolute paths of the machine it was built on and no text search of the source tree will show them:

```sh
# Enumerate every absolute path. The lookbehind is not noise: without it
# the pattern captures from the first slash in a string and reports the
# relative `components/sophgo/video/src/venc.c` as an absolute
# `/sophgo/video/src/venc.c` that is not in the file. Anchoring on `^/`
# instead fails the other way, missing any path embedded in a larger
# string such as `echo 1 > /sys/module/...`.
strings -a capture_jpeg | grep -aoP '(?<![A-Za-z0-9_./+-])/[A-Za-z0-9_./+-]+' | sort -u

# Count occurrences, never lines: a binary has almost no newlines, so
# `grep -c` saturates at 1 and cannot tell "none" from "eight".
strings -a capture_jpeg | grep -ao <token> | wc -l
```

Account for every entry the first command returns rather than filtering any of them out. An entry that looks like noise means the file is the wrong kind for this check — that is the signal, and hiding it behind a filter is how a sweep stops being able to fail.

The offline tests assert this binary reports its frames, by checking it contains the record keywords rather than by pinning its digest. A digest pin would need editing by hand after every legitimate rebuild, and a check that must be edited to keep passing is one the next reader deletes.

What the demo pytest runs, in order:

```sh
./capture_jpeg              /userdata/Models/capture.jpg
./sscma-model               /userdata/Models/scrfd_500m_kps_int8.cvimodel \
                            /userdata/Models/capture.jpg \
                            /userdata/Models/result.jpg
```

The demo uses `/userdata/Models/` rather than `capture_jpeg`'s default `/userdata/local/`, because `device.deploy` has already proved that directory exists and is writable.

Inference output goes to stdout as JSON-ish results. See the source's `solutions/sscma-model/main/main.cpp` for the exact format.

There is no download API on the platform, so the demo brings the annotated frame back through `device.exec` stdout: base64 on the device, decoded client-side, compared against the device-side sha256. `exec` stdout is capped at 256 KiB and base64 inflates 4/3, so the fetch is done in ranges rather than in one call.

### Provenance of the committed `sscma-model`

Committed **unmodified** as built elsewhere — not built, stripped or edited in this repository.

| | |
|---|---|
| sha256 | `77c684f92cea26bce56293588bdd252cf80caa6901b2d49fa796d3c52d9733bb` |
| size | 122144 bytes |
| Source | `solutions/sscma-model/` in the reCamaginedOS tree, against Seeed Studio's [SSCMA-Micro](https://github.com/Seeed-Studio/SSCMA-Micro) at commit `e830d545200ef28406bb765483909928ec2e1baa` (the YOLO26 model generation) |
| Built with | `make build-solution SOLUTION=sscma-model` from the reCamaginedOS tree; the build fetches SSCMA-Micro at that commit itself |

No source patches are applied. In particular there are no MQTT patches: the binary links `libmosquitto.so.1` and `libcares.so.2`, which the device OS ships.

It is built with build-path suppression: no `RPATH`, stripped, and with source paths prefix-mapped out of the strings the compiler embeds. All three are needed — a stripped binary still carries a build-tree `RPATH` if the build adds one, and a `__FILE__`-derived string survives stripping. You can check that on the committed file, which is an ELF executable; both commands are meaningful only on ELF files:

```sh
# No RPATH and no RUNPATH tag of any kind should appear.
readelf -d sscma-model

# Every absolute path in the file (see the note on the lookbehind under
# the capture_jpeg provenance above).
strings -a sscma-model | grep -aoP '(?<![A-Za-z0-9_./+-])/[A-Za-z0-9_./+-]+' | sort -u
```

On the committed file the enumeration returns exactly two entries: `/lib/ld-musl-riscv64v0p7_xthead.so.1`, the ELF interpreter, and `/N`, which is printable bytes inside the `.gnu.hash` table rather than a path. `readelf -d` lists only `NEEDED` libraries and the standard dynamic tags.

**Not yet run on a device.** This build has not been exercised on a camera; the demo's second stage running it is the pending confirmation. The reference output below came from the earlier build this one replaces, which used an older SSCMA-Micro revision, so its numbers are not a prediction for this binary.

If this file is ever replaced, sweep the replacement with the commands above before committing it, and account for every entry the enumeration returns rather than filtering any of them out.

## Running on a live cam

Recamagined ships the CV181X TPU libs but not on the default `LD_LIBRARY_PATH`, and the TPU character devices under `/dev/cvi-*` are `0600 root:root`. So the invocation needs both an explicit library search path and root privileges:

```sh
scp -O capture_jpeg sscma-model scrfd_500m_kps_int8.cvimodel recamera@<cam-ip>:/tmp/

# 1. one frame from the sensor
ssh recamera@<cam-ip> "rm -f /tmp/capture.jpg && sudo -E \
    LD_LIBRARY_PATH=/lib:/usr/lib:/usr/lib64:/mnt/system/lib:/mnt/system/usr/lib:/mnt/system/usr/lib/3rd \
    /tmp/capture_jpeg /tmp/capture.jpg"

# 2. the detector over that frame
ssh recamera@<cam-ip> "sudo -E LD_LIBRARY_PATH=/mnt/system/lib:/mnt/system/usr/lib:/mnt/system/usr/lib/3rd \
    /tmp/sscma-model /tmp/scrfd_500m_kps_int8.cvimodel /tmp/capture.jpg /tmp/result.jpg"
```

The three `/mnt/system` dirs cover: OpenCV + `libcviruntime.so` (in `/mnt/system/lib`), the CV181X ISP / VPSS / VI / VO / sensor drivers (in `/mnt/system/usr/lib`), and third-party libs like `libini.so` (in `/mnt/system/usr/lib/3rd`).

`capture_jpeg` additionally needs `/lib:/usr/lib:/usr/lib64` named explicitly. The image ships no `/etc/ld-musl-*.path`, so musl searches only `/lib:/usr/local/lib:/usr/lib`; `/etc/profile` exports the full set for login shells, but `ssh host '<command>'` never runs it. **A missing library here looks exactly like a capture failure**, which is why the path is spelled out rather than inherited.

## Reference output (2026-07-25, cam 51)

First live run against a recamagined 0.2.2 camera:

```
I engine load model /tmp/scrfd_500m_kps_int8.cvimodel
I model type: 15
x: 0.759033, y: 0.478516, w: 0.345215, h: -0.172852, score: 0.378459 target: 0
x: 0.535156, y: 0.582031, w: 1.414062, h: 1.851562, score: 0.781331 target: 0
x: 0.500000, y: 0.500000, w: 0.015747, h: 0.015747, score: 0.501968 target: 0
I pre: 1ms, infer: 11ms, post: 0ms
```

One high-confidence detection (score ≈ 0.78) — the largest face in the frame — plus two low-score candidates. Latency floor is ~12 ms end-to-end on this SoC / model.

The demo applies no score threshold and asserts nothing about these numbers; it prints every candidate the model reports. A threshold here would be a judgement about the scene, which belongs to the reader of the image rather than to the test.

`sample_faces_detected.jpg` in this directory is the annotated output the binary drew (`x/y/w/h` boxes for each candidate) for that bundled input.

**This is a model-correctness reference, not a demo expectation.** The demo runs on whatever the sensor sees, so its detections are not stable across runs and nothing asserts on them — the offline parser tests in `tests/test_demo_parsing.py` cover the output format, and this image covers the model. Asserting the demo's output against a golden image would be testing the scene in front of the camera.

## `capture_jpeg` build and verification status

Built from `solutions/capture_jpeg/` with the repo's own `make build-solution SOLUTION=capture_jpeg`, which runs cmake inside the builder container, because the cross-compiler is linked against a newer glibc than an EL9 host provides. No source patches. Its `README.md` in that directory carries the reproduction details and the three build flags that keep build-time paths out of the binary.

The committed binary is that build's artifact unmodified. Its sha256, byte count and the properties verified on it are in §Provenance of the committed `capture_jpeg` above, which is the only place in this file that states them — a digest written down twice is two values that can disagree after the next rebuild, and this file has already been wrong that way.

**Verified on hardware.** `capture_jpeg` runs on a device: the sensor initialises, a frame is captured, the detector infers over it in ~11 ms, and the annotated JPEG arrives back with a digest matching the device's own, byte for byte. That run shows the libraries those two code paths actually loaded resolved on the shipped image; it does not enumerate everything the binaries can link against, so a path neither binary took on that run is still untested.

**Still unverified: the capture resolution.** The claim that `capture_jpeg` takes 1920x1080 off encoder channel 1 comes from its source, not from measurement — only 640x640 is proven elsewhere in the tree. The detector writes its own output, so the dimensions of the *annotated* frame describe that file rather than what the sensor produced. The demo now brings the capture frames back as well — the first frame and the settled `capture.jpg` always, and the burst around a rise in encoded size when there is one — so the measurement is a matter of reading the returned capture on a run that has happened, not of fetching anything more.
