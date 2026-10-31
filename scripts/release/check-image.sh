#!/bin/sh
# Refuse to push the CI image unless it is the one to push, and say whether
# the registry already holds its version tag.
#
# Usage: check-image.sh IMAGE VERSION
#
# Refuses when IMAGE:VERSION is not in the local store, was not built from
# HEAD (its org.opencontainers.image.revision label), or carries another
# version label. Then asks the registry for IMAGE:VERSION (`registry.py
# digest`, run by the command in REGISTRY; the Makefile sets it) and prints
# one word on stdout:
#
#   new      the registry has no IMAGE:VERSION;
#   present  the registry's IMAGE:VERSION is this very image (same config
#            digest), as after a push that stopped part way: the version
#            tag is skipped and the moving tags can still be completed.
#
# A registry IMAGE:VERSION that is a different image refuses: released
# version tags are immutable. So does any registry answer other than 404
# MANIFEST_UNKNOWN for this tag, since it proves nothing.
set -eu

podman=${PODMAN:-podman}
registry=${REGISTRY:?set REGISTRY to the command that runs registry.py}
image=$1
version=$2

head=$(git rev-parse HEAD)

id=$($podman image inspect --format '{{.Id}}' "$image:$version" 2>/dev/null) || {
    echo "refusing: $image:$version is not built; run 'make image'" >&2
    exit 1
}
case $id in
    sha256:*) ;;
    *) id=sha256:$id ;;
esac

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

rc=0
remote=$($registry digest "$image:$version") || rc=$?
case $rc in
    3)
        echo "ok   $image:$version ($id) built from HEAD $head, not yet in the registry" >&2
        echo new
        ;;
    0)
        if [ "$remote" != "$id" ]; then
            echo "refusing: the registry's $image:$version is $remote, not this build ($id); released tags are immutable" >&2
            exit 1
        fi
        echo "ok   $image:$version ($id) built from HEAD $head, already in the registry as this image" >&2
        echo present
        ;;
    *)
        echo "refusing: cannot tell whether $image:$version is in the registry" >&2
        exit 1
        ;;
esac
