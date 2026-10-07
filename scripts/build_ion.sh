#!/usr/bin/env bash
# Build and install the ION release named in scripts/ion-release.env.
#
# Usage: scripts/build_ion.sh [PREFIX]
#   PREFIX  install directory (default: .ion/install in the repository)
#
# The script clones the release tag from the upstream NASA/JPL repository,
# refuses to build if the tag does not resolve to the pinned commit, then
# runs the build commands of ION's own CI (autoreconf -fi; ./configure;
# make; make install). It needs git, a C compiler, make, autoconf, automake
# and libtool. A PREFIX that already holds the pinned commit is left as it is.
#
# After it finishes:  export ION_PREFIX=PREFIX
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=ion-release.env
. "$repo_root/scripts/ion-release.env"

prefix="${1:-$repo_root/.ion/install}"
src="${ION_SRC_DIR:-$repo_root/.ion/src}"
stamp="$prefix/.ion-release-commit"

if [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$ION_RELEASE_COMMIT" ] && [ -x "$prefix/bin/ionadmin" ]; then
    echo "ION $ION_RELEASE_TAG ($ION_RELEASE_COMMIT) already installed in $prefix"
    exit 0
fi

rm -rf "$src"
mkdir -p "$(dirname "$src")"
git clone --quiet --depth 1 --branch "$ION_RELEASE_TAG" "$ION_REPOSITORY" "$src"
actual="$(git -C "$src" rev-parse HEAD)"
if [ "$actual" != "$ION_RELEASE_COMMIT" ]; then
    echo "ERROR: tag $ION_RELEASE_TAG is commit $actual, expected $ION_RELEASE_COMMIT" >&2
    exit 1
fi

jobs="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)"
(
    cd "$src"
    autoreconf -fi
    ./configure --prefix="$prefix"
    make -j"$jobs"
    make install
)
echo "$ION_RELEASE_COMMIT" > "$stamp"
echo "Installed ION $ION_RELEASE_TAG ($ION_RELEASE_COMMIT) in $prefix"
echo "export ION_PREFIX=$prefix"
