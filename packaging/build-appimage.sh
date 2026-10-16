#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_ROOT="${BUILD_ROOT:-$ROOT/build/appimage}"
PYTHON="${PYTHON:-python3}"
APPIMAGETOOL="${APPIMAGETOOL:-$(command -v appimagetool || true)}"
APPDIR="$BUILD_ROOT/AppDir"
DIST_DIR="$BUILD_ROOT/dist"
OUTPUT="${OUTPUT:-$ROOT/dist/TuBiblia-x86_64.AppImage}"

if [[ -z "$APPIMAGETOOL" && -x "$BUILD_ROOT/tools/appimagetool-x86_64.AppImage" ]]; then
    APPIMAGETOOL="$BUILD_ROOT/tools/appimagetool-x86_64.AppImage"
fi

if [[ -z "$APPIMAGETOOL" ]]; then
    echo "No se encontró appimagetool. Instálalo o define APPIMAGETOOL=/ruta/appimagetool." >&2
    exit 1
fi

"$PYTHON" -m venv "$BUILD_ROOT/venv"
BUILD_PYTHON="$BUILD_ROOT/venv/bin/python"
"$BUILD_PYTHON" -m pip install --upgrade pip
"$BUILD_PYTHON" -m pip install torch --index-url https://download.pytorch.org/whl/cpu
"$BUILD_PYTHON" -m pip install -e "$ROOT[build]"

rm -rf "$APPDIR" "$DIST_DIR/TuBiblia"
mkdir -p \
    "$APPDIR/usr/bin" \
    "$APPDIR/usr/share/applications" \
    "$APPDIR/usr/share/icons/hicolor/512x512/apps" \
    "$DIST_DIR"

"$BUILD_PYTHON" -m PyInstaller \
    --noconfirm \
    --clean \
    --windowed \
    --onedir \
    --name TuBiblia \
    --distpath "$DIST_DIR" \
    --workpath "$BUILD_ROOT/work" \
    --add-data "$ROOT/tubiblia/assets:tubiblia/assets" \
    --collect-all pocket_tts \
    --copy-metadata pocket-tts \
    --copy-metadata tubiblia \
    "$ROOT/tubiblia/__main__.py"

cp -a "$DIST_DIR/TuBiblia/." "$APPDIR/usr/bin/"
cp "$ROOT/tubiblia/assets/logo_tu_biblia.png" "$APPDIR/tubiblia.png"
cp "$ROOT/tubiblia/assets/logo_tu_biblia.png" \
    "$APPDIR/usr/share/icons/hicolor/512x512/apps/tubiblia.png"
cp "$ROOT/packaging/tubiblia.desktop" "$APPDIR/tubiblia.desktop"
cp "$ROOT/packaging/tubiblia.desktop" "$APPDIR/usr/share/applications/tubiblia.desktop"

cat > "$APPDIR/AppRun" <<'APPRUN'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/TuBiblia" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

mkdir -p "$(dirname "$OUTPUT")"
if [[ "$APPIMAGETOOL" == *.AppImage ]]; then
    ARCH=x86_64 "$APPIMAGETOOL" --appimage-extract-and-run \
        --no-appstream "$APPDIR" "$OUTPUT"
else
    ARCH=x86_64 "$APPIMAGETOOL" --no-appstream "$APPDIR" "$OUTPUT"
fi
rm -rf "$APPDIR" "$DIST_DIR/TuBiblia" "$BUILD_ROOT/work" "$BUILD_ROOT/venv"
printf 'AppImage creado: %s\n' "$OUTPUT"
