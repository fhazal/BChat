#!/bin/bash
# Builds the BChat AppImage: bash packaging/build-linux.sh <version> [out-dir]
# Run in Ubuntu 22.04 (WSL or a container) from a BChat source folder, with a Python venv that has the project's
# requirements and PyInstaller (BCHAT_PY, default python3), patchelf, and appimagetool (APPIMAGETOOL, default
# /opt/appimage/appimagetool). Output: <out-dir>/BChat-<version>-x86_64.AppImage (out-dir defaults to dist).
set -euo pipefail
V="${1:?usage: build-linux.sh <version> [out-dir]}"
OUT="${2:-dist}"
PY="${BCHAT_PY:-python3}"
TOOL="${APPIMAGETOOL:-/opt/appimage/appimagetool}"
cd "$(dirname "$0")/.."
WORK="build/linux"
APPDIR="$WORK/BChat.AppDir"

printf '%s' "$V" > bchat/assets/version.txt
trap 'rm -f bchat/assets/version.txt' EXIT
rm -rf "$WORK/pyi" "$WORK/dist" "$APPDIR"
mkdir -p "$WORK" "$OUT"
"$PY" -m PyInstaller --noconfirm --workpath "$WORK/pyi" --distpath "$WORK/dist" packaging/BChat-linux.spec \
    > "$WORK/pyi-$V.log" 2>&1 || { echo "PYINSTALLER FAILED"; tail -20 "$WORK/pyi-$V.log"; exit 1; }
grep "SLIM: dropped" "$WORK/pyi-$V.log"

# The AppDir: the frozen app in usr/lib/bchat, plus what every AppImage needs at its top (AppRun, .desktop, icon)
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a "$WORK/dist/BChat" "$APPDIR/usr/lib/bchat"
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/bchat/BChat" "$@"
EOF
chmod +x "$APPDIR/AppRun"
cat > "$APPDIR/usr/share/applications/bchat.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=BChat
GenericName=IRC Chat
Comment=Chat on IRC
Exec=BChat %u
Icon=bchat
Terminal=false
Categories=Network;Chat;IRCClient;
StartupWMClass=BChat
MimeType=x-scheme-handler/irc;x-scheme-handler/ircs;
EOF
cp "$APPDIR/usr/share/applications/bchat.desktop" "$APPDIR/bchat.desktop"
cp bchat/assets/bchat.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/bchat.png"
cp bchat/assets/bchat.png "$APPDIR/bchat.png"
ln -sf bchat.png "$APPDIR/.DirIcon"

IMG="$OUT/BChat-$V-x86_64.AppImage"
rm -f "$IMG"
# --appimage-extract-and-run: works without FUSE (WSL, containers)
ARCH=x86_64 "$TOOL" --appimage-extract-and-run --no-appstream "$APPDIR" "$IMG" > "$WORK/appimagetool-$V.log" 2>&1 \
    || { echo "APPIMAGETOOL FAILED"; tail -20 "$WORK/appimagetool-$V.log"; exit 1; }
chmod +x "$IMG"
ls -la "$IMG"
sha256sum "$IMG"
echo BUILD OK
