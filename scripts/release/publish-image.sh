#!/bin/sh
# Push the CI image, then prove every tag pushed resolves to it.
#
# Usage: publish-image.sh [--dry-run] IMAGE VERSION [MOVING_TAG...]
#
# MOVING_TAG is what `registry.py moving-tags` chose (some of X.Y and latest). The
# order is:
#   1. check-image.sh: the local IMAGE:VERSION is built from HEAD, and the
#      registry either lacks VERSION or holds this very image;
#   2. push VERSION (skipped when the registry already holds it), then each
#      moving tag, retagged locally from VERSION;
#   3. read every one of those tags back from the registry (`registry.py
#      digest`, run by the command in REGISTRY) and fail unless it names
#      this image's config digest.
# Every refusal in step 1 comes before the first push. A run that stops in
# step 2 can be repeated with the same local image: VERSION is then
# skipped and the moving tags are completed.
#
# --dry-run runs step 1 and prints the plan without pushing.
set -eu

dry=0
if [ "${1:-}" = "--dry-run" ]; then
    dry=1
    shift
fi
podman=${PODMAN:-podman}
registry=${REGISTRY:?set REGISTRY to the command that runs registry.py}
image=$1
version=$2
shift 2
here=$(dirname "$0")

for t in "$@"; do
    case $t in
        latest | [0-9]*.[0-9]*) ;;
        *)
            echo "refusing: '$t' is not a moving tag (X.Y or latest)" >&2
            exit 1
            ;;
    esac
done

state=$(sh "$here/check-image.sh" "$image" "$version")
id=$($podman image inspect --format '{{.Id}}' "$image:$version")
case $id in
    sha256:*) ;;
    *) id=sha256:$id ;;
esac

push=
if [ "$state" = new ]; then
    push=$version
fi
push="$push $*"
echo "plan $image ($id): push [${push# }], verify [$version $*]"
if [ "$dry" = 1 ]; then
    exit 0
fi

for t in "$@"; do
    $podman tag "$image:$version" "$image:$t"
done
for t in $push; do
    $podman push "$image:$t"
done

failed=0
for t in "$version" "$@"; do
    rc=0
    got=$($registry digest "$image:$t") || rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "FAIL $image:$t does not resolve in the registry after the push" >&2
        failed=1
    elif [ "$got" != "$id" ]; then
        echo "FAIL $image:$t resolves to $got, not the pushed $id" >&2
        failed=1
    else
        echo "ok   $image:$t -> $got"
    fi
done
exit "$failed"
