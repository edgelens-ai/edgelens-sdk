#!/bin/sh
# Refuse to push the CI image unless it is the one to push.
#
# Usage: check-image.sh IMAGE VERSION TAG...
#
# Refuses when IMAGE:VERSION is not built locally, was not built from HEAD
# (its org.opencontainers.image.revision label), or carries another version
# label; when any TAG is missing locally or points at a different image; and
# when IMAGE:VERSION already exists in the registry. Released tags are
# immutable, so an existing version is never pushed again. The registry
# lookup may fail only with "not found" (podman says "manifest unknown",
# docker "no such manifest"); any other failure (network, auth)
# refuses too, because it proves nothing about the tag.
set -eu

podman=${PODMAN:-podman}
image=$1
version=$2
shift 2

head=$(git rev-parse HEAD)

id=$($podman image inspect --format '{{.Id}}' "$image:$version" 2>/dev/null) || {
    echo "refusing: $image:$version is not built; run 'make image'" >&2
    exit 1
}

labels=$($podman image inspect "$image:$version" \
    --format '{{index .Config.Labels "org.opencontainers.image.revision"}} {{index .Config.Labels "org.opencontainers.image.version"}}')
revision=${labels% *}
labelled=${labels#* }
if [ "$revision" != "$head" ]; then
    echo "refusing: $image:$version was built from '$revision' but HEAD is $head; run 'make image'" >&2
    exit 1
fi
if [ "$labelled" != "$version" ]; then
    echo "refusing: $image:$version is labelled version '$labelled'" >&2
    exit 1
fi

for tag in "$@"; do
    tag_id=$($podman image inspect --format '{{.Id}}' "$image:$tag" 2>/dev/null) || tag_id=
    if [ "$tag_id" != "$id" ]; then
        echo "refusing: $image:$tag is not the image built as $image:$version; run 'make image'" >&2
        exit 1
    fi
done

if out=$($podman manifest inspect "$image:$version" 2>&1); then
    echo "refusing: $image:$version already exists in the registry; released tags are immutable" >&2
    exit 1
fi
case $out in
    *"manifest unknown"* | *"not found"* | *"NOT_FOUND"* | *"no such manifest"*) ;;
    *)
        echo "refusing: cannot tell whether $image:$version is in the registry:" >&2
        echo "$out" >&2
        exit 1
        ;;
esac

echo "ok   $image:$version ($id) built from HEAD $head, not yet in the registry"
