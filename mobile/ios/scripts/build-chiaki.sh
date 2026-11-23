#!/bin/bash
# Builds the Chiaki Remote Play C library for iPhone (device only) from third_party/pylux,
# the same way Pylux's own CI does, and combines everything into libchiaki_complete.a.
# Output: third_party/pylux/ios/build-iphoneos/libchiaki_complete.a (+ generated headers).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IOS="$HERE/third_party/pylux/ios"
OUT="$IOS/build-iphoneos"

if [ -f "$OUT/libchiaki_complete.a" ]; then
    echo "libchiaki_complete.a already built."
    exit 0
fi

if [ ! -f "$IOS/ios.toolchain.cmake" ]; then
    curl -fsSL -o "$IOS/ios.toolchain.cmake" \
        https://raw.githubusercontent.com/leetal/ios-cmake/master/ios.toolchain.cmake
fi

cmake -S "$IOS" -B "$OUT" -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE="$IOS/ios.toolchain.cmake" \
    -DPLATFORM=OS64 \
    -DCMAKE_BUILD_TYPE=Release \
    -DUSE_LIBIDN2=OFF \
    -DCURL_USE_LIBPSL=OFF \
    -DUSE_NGHTTP2=OFF \
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5
cmake --build "$OUT" --config Release --target chiaki-lib

find "$OUT" -name "*.a" ! -name "libchiaki_complete.a" -print0 \
    | xargs -0 libtool -static -o "$OUT/libchiaki_complete.a"
ls -lh "$OUT/libchiaki_complete.a"
