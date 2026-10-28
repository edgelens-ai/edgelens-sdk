# Convenience wrapper around the steps in DEMO.md.
#
# DEMO.md is the primary instructions and this mirrors them — it does not
# replace them. The pytest command below is the one DEMO.md documents,
# character for character; if the two ever differ, this file is wrong.
#
# Run it from anywhere, including the repository root:
#
#     make -C examples/pytest demo
#
# The target exists because the demo needs two setup steps before pytest,
# and forgetting the second produces "No API key provided" — which reads
# as a rejected key rather than as a key that was never loaded.

# Extra arguments for pytest. Empty by default, so `make demo` runs exactly
# the documented command. Useful for a dry run that allocates no hardware:
#
#     make -C examples/pytest demo PYTEST_ARGS=--collect-only
#
PYTEST_ARGS ?=

.PHONY: demo test test-stage-gate test-displayed-digest help

## demo: run the end-to-end demo against a real device
# Runs in the same image as the offline tests, for the same reason: nothing
# is installed on the host, and the dependencies come from a file the image
# build consumes rather than from an environment someone constructed by
# hand. One image rather than two keeps that declaration in one place,
# which is the whole point of having it.
#
# Three flags differ from the offline target, and each is a property of
# this run rather than of the image:
#
#   --network host    the demo talks to the platform, which the offline
#                     tests are denied on purpose
#   (no :ro)          the run writes its artifacts into this tree and
#                     reads them back; the offline tests must not write
#   --env-file        the key and the base URL come from .env, which stays
#                     gitignored. Passed as a file so the key never
#                     appears in a command line, where it would reach the
#                     process table and anything reading it
#
# A writable HOME is needed too, because rootless podman leaves it at "/",
# but that is set in the image rather than here: every caller needs it and
# none of them should have to know.
demo:
	$(PODMAN) run --rm --network host \
	  --env-file ./.env \
	  -v $(CURDIR):/workspace:Z -w /workspace \
	  $(CI_IMAGE) \
	  pytest tests/test_demo_end_to_end.py -v -s --edgelens-os=recamagined $(PYTEST_ARGS)

## test: run the offline tests in a container — no device, no API key, nothing installed locally
# Runs in a throwaway container rather than a local virtualenv, because
# nothing is installed on the host. There was previously no target that
# created the virtualenv this file assumed, so the missing step became a
# manual package install — which is not a supported route and should not
# be reinvented here.
#
# It runs in the repo's own CI image, which already carries Python 3.12,
# pytest and the SDK packages — so nothing is installed at run time and
# the target works with the network off. Build it once with
# `make -C ../.. image`.
#
# --network none is deliberate and is the point: these tests are offline
# by definition, so denying the network means a test that quietly starts
# depending on a live service fails here rather than in the demo. Note
# that this only works because the image is pre-built; installing a
# dependency at run time cannot coexist with it.
#
# The tree is mounted read-only: these tests read fixtures and must not
# be able to rewrite them.
PODMAN ?= podman
CI_IMAGE ?= docker.io/edgelensai/edgelens-sdk:$(shell cat ../../VERSION)

test:
	$(PODMAN) run --rm --network none \
	  -v $(CURDIR):/workspace:ro,Z -w /workspace \
	  $(CI_IMAGE) \
	  pytest tests/test_demo_parsing.py -v

## test-stage-gate: run only the tests that pin the gate between the two demo stages
# Named by test rather than by file, because the point of the target is to
# be re-taken: delete the skip out of `_require_stage_one` and this is the
# one command that says so, in a second rather than in the whole suite.
#
# It does not replace `test`, which stays the whole offline suite — these
# tests run there too and that is where a regression is actually caught.
# This exists so the probe is cheap, and so the next reader can confirm
# the pin still bites without reading this file to work out how.
#
# The gate's own code path only ever executes against a rented device, so
# nothing else offline would notice it going away. Same image, same
# --network none, same read-only mount as `test`, for the same reasons.
STAGE_GATE_TESTS = \
  tests/test_demo_parsing.py::test_the_gate_starts_shut_and_only_a_pass_opens_it \
  tests/test_demo_parsing.py::test_the_skip_reason_names_the_failure_rather_than_announcing_one \
  tests/test_demo_parsing.py::test_every_red_the_first_stage_can_produce_shuts_the_gate \
  tests/test_demo_parsing.py::test_the_gate_stops_the_second_stage_when_the_first_one_failed \
  tests/test_demo_parsing.py::test_the_gate_is_transparent_once_the_first_stage_has_passed \
  tests/test_demo_parsing.py::test_the_gate_is_consulted_before_the_second_stage_does_anything

test-stage-gate:
	$(PODMAN) run --rm --network none \
	  -v $(CURDIR):/workspace:ro,Z -w /workspace \
	  $(CI_IMAGE) \
	  pytest $(STAGE_GATE_TESTS) -v

## test-displayed-digest: run only the tests that pin the displayed code against its digest
# Named by test for the same reason the gate target is: the question it
# answers is "does the digest check still bite", and that has to be
# answerable in a second without reading either test file.
#
# What it pins is the one comparison nothing used to make. The address
# serves a thumbnail its host renders on demand, so it does not pin the
# bytes; every quiet-zone margin figure here is a property of the bytes;
# and the device fetches them itself, so they never reach the harness.
# The offline suite can only hash the committed copy, which a re-render
# at that address leaves untouched.
#
# These tests run in the whole offline suite too, and that is where a
# regression is caught. The refusal half is the half worth re-taking by
# hand: a digest check that cannot fail is the defect this replaced.
#
# Same image, same --network none and same read-only mount as `test`,
# for the same reasons — and here the denied network is also the
# assertion, because the verification takes bytes rather than a url
# precisely so that it can be pinned with the network off.
DISPLAYED_DIGEST_TESTS = \
  tests/test_demo_parsing.py::test_the_displayed_code_is_the_one_committed_here \
  tests/test_demo_parsing.py::test_the_measured_artifact_is_accepted_and_anything_else_is_refused \
  tests/test_demo_parsing.py::test_the_refusal_names_both_digests_and_the_address_they_came_from \
  tests/test_demo_parsing.py::test_a_fetch_that_failed_is_reported_rather_than_read_as_a_mismatch \
  tests/test_demo_parsing.py::test_the_verification_fetches_nothing_itself \
  tests/test_demo_parsing.py::test_the_served_bytes_are_checked_before_the_window_is_spent \
  tests/test_demo_parsing.py::test_the_run_stops_when_the_address_serves_different_bytes \
  tests/test_demo_parsing.py::test_the_run_continues_when_the_fetch_itself_fails \
  tests/test_demo_parsing.py::test_the_check_is_transparent_when_the_address_still_serves_the_artifact \
  tests/test_demo_parsing.py::test_the_refusal_is_attributed_like_every_other_red

# PYTEST_ARGS is honoured here and not in `test`, because re-taking this
# means reading the refusal rather than counting a pass:
#
#     make -C examples/pytest test-displayed-digest PYTEST_ARGS=-s
#
# prints the message a mismatch produces, which is the thing worth
# checking by eye — both digests and the address that served the wrong
# bytes have to be in it, or the failure sends its reader back to the
# source to work out what was compared with what.
test-displayed-digest:
	$(PODMAN) run --rm --network none \
	  -v $(CURDIR):/workspace:ro,Z -w /workspace \
	  $(CI_IMAGE) \
	  pytest $(DISPLAYED_DIGEST_TESTS) -v $(PYTEST_ARGS)

## help: list the targets
help:
	@sed -n 's/^## //p' $(MAKEFILE_LIST)
