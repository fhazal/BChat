#!/bin/bash
# Builds the BChat Flatpak from THIS source folder: bash packaging/flatpak/build-flatpak.sh [version] [out-dir]
# Run on Linux (Fedora, or Ubuntu 22.04 in WSL) with flatpak and the org.flatpak.Builder flatpak, which brings
# flatpak-builder and flatpak-builder-lint:  flatpak install flathub org.flatpak.Builder
# The KDE runtime/SDK and io.qt.PySide.BaseApp are installed from Flathub on the first build if missing, into your
# user installation (FP_SCOPE=--system to use the system one, e.g. as root in WSL). The source folder must not be
# under /root: the builder's sandbox can't see it.
# The manifest in this folder builds the released tag from GitHub (that is what Flathub builds); this script
# builds a copy of it whose bchat source is this folder instead, so unreleased code can be tried. Only files git
# knows about (committed or new, not ignored) are copied.
# version: what About shows (default: the newest <release> in the metainfo). out-dir defaults to dist.
# Output: <out-dir>/BChat-<version>.flatpak and the repo in build/flatpak/repo, then the linter's verdict on the
# manifest and the repo. Try it:  flatpak install --user <out-dir>/BChat-<version>.flatpak
#                                 flatpak run io.github.fhazal.BChat
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/../.."
ROOT="$(pwd)"
APP=io.github.fhazal.BChat
V="${1:-$(sed -n 's/.*<release version="\([^"]*\)".*/\1/p' "$HERE/$APP.metainfo.xml" | head -n1)}"
OUT="$(mkdir -p "${2:-dist}" && cd "${2:-dist}" && pwd)"      # absolute: the builder's sandbox has its own cwd
SCOPE="${FP_SCOPE:---user}"
WORK="$ROOT/build/flatpak"
BUILDER=(flatpak run org.flatpak.Builder)
LINT=(flatpak run --command=flatpak-builder-lint org.flatpak.Builder)

rm -rf "$WORK/src" "$WORK/manifest"
mkdir -p "$WORK/src" "$WORK/manifest" "$OUT"

# the source: what git knows about, or (no .git, e.g. an unpacked archive) everything but build output
if git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    git -C "$ROOT" ls-files -z -c -o --exclude-standard | while IFS= read -r -d '' f; do
        [ -e "$f" ] && printf '%s\0' "$f"
    done | tar --null -T - -cf - | tar -xf - -C "$WORK/src"
else
    tar --exclude=./build --exclude=./dist --exclude=./.git -cf - . | tar -xf - -C "$WORK/src"
fi
printf '%s' "$V" > "$WORK/src/bchat/assets/version.txt"

# the manifest copy: the git source (url, tag, commit, x-checker-data) becomes a dir source
cp "$HERE/$APP.desktop" "$HERE/$APP.metainfo.xml" "$HERE"/python3-deps.* "$WORK/manifest/"
python3 - "$HERE/$APP.yml" "$WORK/manifest/$APP.yml" "$WORK/src" <<'EOF'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
new, n = re.subn(r"( +)- type: git\n(?:\1  .*\n)+", lambda m: f"{m.group(1)}- type: dir\n{m.group(1)}  path: {sys.argv[3]}\n", text)
if n != 1:
    sys.exit("build-flatpak.sh: expected one git source in the manifest, found %d" % n)
open(sys.argv[2], "w", encoding="utf-8").write(new)
EOF

flatpak remote-add "$SCOPE" --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
"${BUILDER[@]}" "$SCOPE" --install-deps-from=flathub --force-clean --disable-rofiles-fuse \
    --mirror-screenshots-url=https://dl.flathub.org/media/ --repo="$WORK/repo" \
    --state-dir="$WORK/.flatpak-builder" "$WORK/build-dir" "$WORK/manifest/$APP.yml" \
    > "$WORK/build-$V.log" 2>&1 || { echo "FLATPAK-BUILDER FAILED"; tail -30 "$WORK/build-$V.log"; exit 1; }

BUNDLE="$OUT/BChat-$V.flatpak"
rm -f "$BUNDLE"
flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo "$WORK/repo" "$BUNDLE" "$APP"
ls -la "$BUNDLE"
sha256sum "$BUNDLE"

# Flathub's linter: the real manifest (as submitted) and the built repo; problems are listed, not fatal here
echo "--- lint manifest"
"${LINT[@]}" manifest "$HERE/$APP.yml" && echo "manifest: no problems" || true
echo "--- lint repo"
"${LINT[@]}" repo "$WORK/repo" && echo "repo: no problems" || true
echo BUILD OK
