#!/bin/sh
# Build a .deb from dist/mandalawerx (run pyinstaller first).
# Usage: packaging/build-deb.sh <version>
set -eu
VER="$1"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
STAGE=$(mktemp -d)/mandalawerx-$VER
mkdir -p "$STAGE/DEBIAN" "$STAGE/usr/lib" "$STAGE/usr/bin" \
    "$STAGE/usr/share/applications" \
    "$STAGE/usr/share/icons/hicolor/256x256/apps" \
    "$STAGE/usr/share/icons/hicolor/scalable/apps" \
    "$STAGE/usr/doc/mandalawerx" "$STAGE/usr/share/doc/mandalawerx"

cp -r "$ROOT/dist/mandalawerx" "$STAGE/usr/lib/mandalawerx"
chmod -R u=rwX,go=rX "$STAGE/usr/lib/mandalawerx"

printf '#!/bin/sh\nexec /usr/lib/mandalawerx/mandalawerx "$@"\n' \
    > "$STAGE/usr/bin/mandalawerx"
chmod 755 "$STAGE/usr/bin/mandalawerx"

install -m 644 "$ROOT/packaging/mandalawerx.desktop" \
    "$STAGE/usr/share/applications/mandalawerx.desktop"
install -m 644 "$ROOT/Images/mandalawerx-icon.svg" \
    "$STAGE/usr/share/icons/hicolor/scalable/apps/mandalawerx.svg"
install -m 644 "$ROOT/Images/mandalawerx-icon-1024.png" \
    "$STAGE/usr/share/icons/hicolor/256x256/apps/mandalawerx.png"

printf 'Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\nUpstream-Name: Mandala-Werx\nSource: https://github.com/thetech207/Mandala-Werx\n' \
    > "$STAGE/usr/share/doc/mandalawerx/copyright"

cat > "$STAGE/DEBIAN/control" <<CTL
Package: mandalawerx
Version: $VER
Section: graphics
Priority: optional
Architecture: amd64
Maintainer: thetech207 <https://github.com/thetech207>
Depends: libc6, libstdc++6, libgl1, libegl1, libxkbcommon0, libdbus-1-3, libfontconfig1, libglib2.0-0t64
Description: Circular mandala illustration editor
 A vector graphics editor for circular mandala artwork: draw in one
 segment of a polar grid and every stroke is rotated (optionally
 mirrored) into all remaining segments. Vector shapes, pen/pencil
 tools, SVG and raster import with background keying, layers,
 and PNG/JPEG/TIFF/WebP/SVG/PDF export.
CTL

dpkg-deb --build --root-owner-group "$STAGE" \
    "$ROOT/dist/mandalawerx_${VER}_amd64.deb"
echo "built dist/mandalawerx_${VER}_amd64.deb"
