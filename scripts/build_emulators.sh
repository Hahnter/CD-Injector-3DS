#!/usr/bin/env bash
# Builds everything CD Injector 3DS bundles into resources/:
#   resources/cores/{temperpce,picodrive}/  patched emulator ELF + RSF + RomFS assets
#   resources/tools/linux/                  makerom (official release), bannertool
#   resources/tools/windows/                makerom.exe and bannertool.exe (both the authors' own releases)
#   dist/emulator-source.tar.gz             complete patched emulator source (PicoDrive license)
#
# Needs: Linux or WSL with devkitPro (3ds-dev, 3ds-zlib), git, make, gettext, curl, unzip. With
#        BANNERTOOL_WIN_FROM_SOURCE=1, bannertool.exe is compiled here instead of downloaded, which also needs
#        g++-mingw-w64-x86-64.
set -euo pipefail

FORK_URL=https://github.com/R-YaTian/emus3ds.git
FORK_COMMIT=a10138fc13c2c90e2a520f5717be002d932d87c0   # the patch is written against this
BANNERTOOL_URL=https://github.com/diasurgical/bannertool.git
BANNERTOOL_COMMIT=16d8c5a0ce02a5e06e64ab42275132fca57c04a2   # the exact version that was built and tested
# bannertool.exe: the author's release build of the same code (its Windows files are from 2021 and many people have
# downloaded them), checked against these SHA-256 sums before use. The program code hasn't changed since 2020: run with
# BANNERTOOL_WIN_FROM_SOURCE=1 to compile it from the commit above instead, which gives the same banners.
BANNERTOOL_RELEASE=https://github.com/diasurgical/bannertool/releases/download/1.2.0/bannertool.zip
BANNERTOOL_ZIP_SHA=69768596f836acb3e3aeaa66e47c6ba560dde813c6dfcd33c8afc25fe29b7524
BANNERTOOL_WIN_SHA=62a20363f7cdebd7a9564beb52dc0ae80838ca35d9f35166d5a632a0844c93d4
# makerom: the official release (MIT), checked against these SHA-256 sums before use
MAKEROM_RELEASE=https://github.com/3DSGuy/Project_CTR/releases/download/makerom-v0.18.4
MAKEROM_WIN_ZIP=makerom-v0.18.4-win_x86_64.zip
MAKEROM_WIN_SHA=d743507dc66d4c6f8efcce05ff8f5f47163a60e54e0e0c57fa12ec2f54acdf2f
MAKEROM_LINUX_ZIP=makerom-v0.18.4-ubuntu_x86_64.zip
MAKEROM_LINUX_SHA=dd596854718c195c6e3229286be485b122921715555af8ae5cf8e9a465d9f970

REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${WORK:-$HOME/cd-injector-3ds-work}"
RES="$REPO/resources"

export DEVKITPRO="${DEVKITPRO:-/opt/devkitpro}"
export DEVKITARM="${DEVKITARM:-$DEVKITPRO/devkitARM}"
export PATH="$DEVKITPRO/tools/bin:$PATH"
[ -x "$DEVKITARM/bin/arm-none-eabi-gcc" ] || { echo "devkitARM not found at $DEVKITARM"; exit 1; }

mkdir -p "$WORK" "$RES/cores" "$RES/tools/linux" "$RES/tools/windows" "$REPO/dist"

# --- emulators -----------------------------------------------------------
[ -d "$WORK/emus3ds/.git" ] || git clone "$FORK_URL" "$WORK/emus3ds"
cd "$WORK/emus3ds"
git fetch -q origin
git checkout -q -f "$FORK_COMMIT"
git clean -qfdx
git apply "$REPO/patches/autoboot-forwarder.patch"

tar --exclude=.git -czf "$REPO/dist/emulator-source.tar.gz" -C "$WORK" emus3ds

for core in temperpce picodrive; do
    echo "== building $core"
    make -f "$core-make" -j"$(nproc)" > "$WORK/$core-build.log" 2>&1 || { tail -30 "$WORK/$core-build.log"; exit 1; }
    dest="$RES/cores/$core"
    rm -rf "$dest" && mkdir -p "$dest"
    cp "${core}_3ds.elf"                 "$dest/emulator.elf"
    cp "src/cores/$core/assets/cia.rsf"  "$dest/cia.rsf"
    cp -r "src/cores/$core/assets/romfs" "$dest/romfs"
done

# --- makerom (official release, hash-checked) ------------------------------
mkdir -p "$WORK/makerom"
for pair in "$MAKEROM_WIN_ZIP $MAKEROM_WIN_SHA windows makerom.exe" "$MAKEROM_LINUX_ZIP $MAKEROM_LINUX_SHA linux makerom"; do
    set -- $pair
    curl -fsSL -o "$WORK/makerom/$1" "$MAKEROM_RELEASE/$1"
    echo "$2  $WORK/makerom/$1" | sha256sum -c --quiet - || { echo "makerom download $1 has the wrong SHA-256"; exit 1; }
    unzip -o -q -d "$WORK/makerom/$3" "$WORK/makerom/$1"
    cp "$WORK/makerom/$3/$4" "$RES/tools/$3/$4"
done

# --- bannertool (Linux + Windows) ----------------------------------------
[ -d "$WORK/bannertool/.git" ] || git clone -q --recursive "$BANNERTOOL_URL" "$WORK/bannertool"
git -C "$WORK/bannertool" fetch -q origin
git -C "$WORK/bannertool" checkout -q -f "$BANNERTOOL_COMMIT"
git -C "$WORK/bannertool" submodule update -q --init --recursive
targets="NATIVE"
[ "${BANNERTOOL_WIN_FROM_SOURCE:-0}" = 1 ] && targets="NATIVE WIN64"
for target in $targets; do
    echo "== building bannertool ($target)"
    make -C "$WORK/bannertool" clean >/dev/null 2>&1 || true
    make -C "$WORK/bannertool" TARGET=$target -j"$(nproc)" > "$WORK/bannertool-$target.log" 2>&1 || true   # zip step may fail
    if [ $target = NATIVE ]; then
        cp "$WORK/bannertool/output/linux-x86_64/bannertool" "$RES/tools/linux/bannertool"
    else
        cp "$WORK/bannertool/output/windows-x86_64/bannertool.exe" "$RES/tools/windows/bannertool.exe"
    fi
done

if [ "${BANNERTOOL_WIN_FROM_SOURCE:-0}" != 1 ]; then
    echo "== bannertool.exe (the author's release, hash-checked)"
    mkdir -p "$WORK/bannertool-release"
    curl -fsSL -o "$WORK/bannertool-release.zip" "$BANNERTOOL_RELEASE"
    echo "$BANNERTOOL_ZIP_SHA  $WORK/bannertool-release.zip" | sha256sum -c --quiet - \
        || { echo "the bannertool download has the wrong SHA-256"; exit 1; }
    unzip -o -q -d "$WORK/bannertool-release" "$WORK/bannertool-release.zip"
    echo "$BANNERTOOL_WIN_SHA  $WORK/bannertool-release/windows-x86_64/bannertool.exe" | sha256sum -c --quiet - \
        || { echo "bannertool.exe in the download has the wrong SHA-256"; exit 1; }
    cp "$WORK/bannertool-release/windows-x86_64/bannertool.exe" "$RES/tools/windows/bannertool.exe"
fi

chmod +x "$RES/tools/linux/"*
echo "== done"
find "$RES" -maxdepth 3 -type f | sort
