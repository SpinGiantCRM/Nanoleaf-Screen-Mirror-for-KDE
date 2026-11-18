#!/usr/bin/env bash
# Test the nanoleaf-hdr plugin inside a nested Hyprland, never the running desktop.
#
# A nested Hyprland window opens with one output forced to PQ HDR. A colour-managed
# test window shows grey patches at 100, 203, 465 and 1000 nits. The script then
# captures them: with normal 8-bit capture, with the plugin's 10-bit capture, and
# again after unloading. Only numbers are printed; no image is saved.
#
#   tools/hyprland-hdr-capture/test/nested-test.sh [MAX_NITS]
#
# MAX_NITS (default 10000) is the nested output's peak. At 10000 Hyprland does not
# tone-map the patches, so the plugin's capture must return the patch codes exactly.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
PEAK=${1:-10000}
WORK=$(mktemp -d)
trap 'kill ${LPID:-} ${HPID:-} 2>/dev/null || true; rm -rf "$WORK"' EXIT

make -s -C "$ROOT/plugin" >/dev/null
make -s -C "$ROOT/probe" >/dev/null
sed -E "s/([^_])max_luminance = [0-9]+/\1max_luminance = $PEAK/" "$HERE/nested-hdr.lua" > "$WORK/hyprland.lua"

before=$(hyprctl instances -j | python3 -c "import json,sys;print(' '.join(i['instance'] for i in json.load(sys.stdin)))")
timeout 300 Hyprland -c "$WORK/hyprland.lua" > "$WORK/log.txt" 2>&1 &
HPID=$!
sleep 6
read -r NEW SOCK < <(hyprctl instances -j | python3 -c "
import json,sys
b='$before'.split()
l=[i for i in json.load(sys.stdin) if i['instance'] not in b]
print(l[0]['instance'], l[0]['wl_socket'])")
h() { hyprctl --instance "$NEW" "$@"; }

WAYLAND_DISPLAY=$SOCK "$ROOT/probe/nanoleaf-hdr-ladder" > "$WORK/ladder.txt" 2>&1 &
LPID=$!
sleep 2
tail -1 "$WORK/ladder.txt"

read -r -a PATCH < <(h clients -j | python3 -c "
import json,sys
c=[c for c in json.load(sys.stdin) if c['class']=='nanoleaf-hdr-ladder'][0]
(x,y),(w,hh)=c['at'],c['size']
print(' '.join('--patch %d,%d,20,20'%(x+w*(i+0.5)/4-10, y+hh/2-10) for i in range(4)))")
CENTRES=$(printf '%s\n' "${PATCH[@]}" | grep -v patch | python3 -c "
import sys
print(' '.join('%d,%d'%(int(a.split(',')[0])+10, int(a.split(',')[1])+10) for a in sys.stdin.read().split()))")

grim8() {
    WAYLAND_DISPLAY=$SOCK timeout 10 grim -t ppm -o WAYLAND-1 - | python3 -c "
import sys
d=sys.stdin.buffer.read(); parts=d.split(b'\n',3); w,h=map(int,parts[1].split()); px=parts[3]
print('   8-bit codes:', [px[(int(c.split(',')[1])*w+int(c.split(',')[0]))*3] for c in '$CENTRES'.split()])"
}
probe() {
    local out
    out=$(WAYLAND_DISPLAY=$SOCK timeout 20 "$ROOT/probe/nanoleaf-hdr-probe" "${PATCH[@]}" 2>&1) || { echo "   $out"; return 0; }
    printf '%s' "$out" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for n,p in zip((100,203,465,1000),d['patches']):
    print('   %4d nits shown -> code %.1f = %.1f nits'%(n,p['mean_code'][1],p['pq_nits'][1]))"
}

echo "1) No plugin, normal 8-bit capture:"; grim8
echo "2) No plugin, 10-bit capture:"; probe
h plugin load "$ROOT/plugin/nanoleaf-hdr.so" >/dev/null
echo "3) Plugin loaded, 10-bit capture by the opted-in probe:"; probe
echo "4) Plugin loaded, normal 8-bit capture by another client:"; grim8
h nanoleafhdr | python3 -c "import json,sys;print('   plugin counters:',json.load(sys.stdin)['counters'])"
h plugin unload "$ROOT/plugin/nanoleaf-hdr.so" >/dev/null
echo "5) Plugin unloaded, normal 8-bit capture:"; grim8
h version >/dev/null && echo "   nested Hyprland still running after unload"
if grep -qE "Assertion|crashed" "$WORK/log.txt"; then echo "nested Hyprland reported a crash"; exit 1; fi
