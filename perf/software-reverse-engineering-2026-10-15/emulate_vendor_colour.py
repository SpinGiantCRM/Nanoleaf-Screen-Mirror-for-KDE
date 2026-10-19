# Offline CPU emulation of selected arithmetic routines, not Windows execution.
import argparse
import collections
import hashlib
import json
import math
import random
import struct
from pathlib import Path

import pefile
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_64, Uc
from unicorn import x86_const as x86

parser = argparse.ArgumentParser(
    description="Offline emulation of pinned vendor colour math only; no hardware access"
)
parser.add_argument("dll", type=Path)
DLL = parser.parse_args().dll
if not DLL.is_file():
    raise SystemExit("Input must be a regular local file")
with DLL.open("rb") as source:
    dll_bytes = source.read(1024 * 1024 + 1)
if (
    hashlib.sha256(dll_bytes).hexdigest()
    != "a86758c34040055585436d2d96f15e21e084708815b3426a59c495fc97729a7e"
):
    raise SystemExit("Refusing a DLL that differs from the pinned inspected 3.0.1 library")
pe = pefile.PE(data=dll_bytes)
image = pe.OPTIONAL_HEADER.ImageBase
uc = Uc(UC_ARCH_X86, UC_MODE_64)
uc.mem_map(image, 0xA000)
uc.mem_write(image, pe.get_memory_mapped_image())
STACK = 0x1000000
HEAP = 0x2000000
STUB = 0x4000000
STOP = STUB + 0xFF0
uc.mem_map(STACK, 0x100000)
uc.mem_map(HEAP, 0x10000)
uc.mem_map(STUB, 0x1000)
imports = {}
counts = collections.Counter()
for desc in pe.DIRECTORY_ENTRY_IMPORT:
    for entry in desc.imports:
        name = entry.name.decode() if entry.name else str(entry.ordinal)
        addr = STUB + len(imports) * 16
        imports[addr] = name
        uc.mem_write(entry.address, struct.pack("<Q", addr))
        uc.mem_write(addr, b"\xc3")


def value(reg, fmt):
    size = struct.calcsize(fmt)
    return struct.unpack(fmt, uc.reg_read(reg).to_bytes(16, "little")[:size])[0]


def write(value, fmt):
    uc.reg_write(x86.UC_X86_REG_XMM0, int.from_bytes(struct.pack(fmt, value), "little"))


def hook(emu, address, size, user):
    if address not in imports:
        return
    name = imports[address]
    counts[name] += 1
    if name in ("fmaxf", "fminf"):
        a, b = value(x86.UC_X86_REG_XMM0, "<f"), value(x86.UC_X86_REG_XMM1, "<f")
        write(max(a, b) if name == "fmaxf" else min(a, b), "<f")
    elif name == "round":
        a = value(x86.UC_X86_REG_XMM0, "<d")
        write(math.copysign(math.floor(abs(a) + 0.5), a), "<d")
    else:
        raise RuntimeError("Refusing unimplemented/OS import " + name)


uc.hook_add(UC_HOOK_CODE, hook)


def call(rva, *args):
    for reg in [
        x86.UC_X86_REG_RAX,
        x86.UC_X86_REG_RBX,
        x86.UC_X86_REG_RBP,
        x86.UC_X86_REG_RSI,
        x86.UC_X86_REG_RDI,
        x86.UC_X86_REG_R8,
        x86.UC_X86_REG_R9,
        x86.UC_X86_REG_R10,
        x86.UC_X86_REG_R11,
        x86.UC_X86_REG_R12,
        x86.UC_X86_REG_R13,
        x86.UC_X86_REG_R14,
        x86.UC_X86_REG_R15,
    ]:
        uc.reg_write(reg, 0)
    for reg in range(x86.UC_X86_REG_XMM0, x86.UC_X86_REG_XMM15 + 1):
        uc.reg_write(reg, 0)
    for reg, arg in zip(
        [x86.UC_X86_REG_RCX, x86.UC_X86_REG_RDX, x86.UC_X86_REG_R8, x86.UC_X86_REG_R9],
        args,
        strict=False,
    ):
        uc.reg_write(reg, arg)
    rsp = STACK + 0xFF000 - 8
    uc.mem_write(rsp, struct.pack("<Q", STOP))
    uc.reg_write(x86.UC_X86_REG_RSP, rsp)
    uc.reg_write(x86.UC_X86_REG_MXCSR, 0x1F80)
    uc.emu_start(image + rva, STOP, timeout=1000000, count=100000)
    assert uc.reg_read(x86.UC_X86_REG_RIP) == STOP, "Instruction/time budget reached"
    return uc.reg_read(x86.UC_X86_REG_RAX)


objects = {}
for profile, params, cct in [(1, 0x4648, 0x4660), (2, 0x47D8, 0x47F0), (3, 0x44B8, 0x44D0)]:
    obj = HEAP + profile * 0x100
    call(0x1040, obj, image + params, image + cct)
    objects[profile] = obj
samples = [
    [0, 0, 0],
    [1, 1, 1],
    [4, 4, 4],
    [8, 8, 8],
    [64, 64, 64],
    [128, 128, 128],
    [255, 255, 255],
    [255, 0, 0],
    [0, 255, 0],
    [0, 0, 255],
    [255, 255, 0],
    [0, 255, 255],
    [255, 0, 255],
    [128, 64, 32],
]


def calibrate(profile, rgb):
    uc.mem_write(HEAP + 0x1000, bytes(rgb))
    uc.mem_write(HEAP + 0x2000, b"\0" * 8)
    call(0x12C4, objects[profile], HEAP + 0x2000, HEAP + 0x1000)
    return list(uc.mem_read(HEAP + 0x2000, 3))


results = [
    {"input": rgb, "profiles": {str(p): calibrate(p, rgb) for p in objects}} for rgb in samples
]
# Exhaustive neutral ramp checks plus deterministic broad RGB inputs.
ramp = {str(p): [calibrate(p, [i] * 3) for i in range(256)] for p in objects}
random.seed(8202)
rgbs = [[random.randrange(256) for _ in range(3)] for _ in range(256)]
broad = {str(p): [calibrate(p, c) for c in rgbs] for p in objects}
repeat = {str(p): [calibrate(p, c) for c in rgbs] for p in objects}
assert broad == repeat
# Disabling the native object's calibration flag must make the exact routine identity.
identity_checks = 0
for profile, obj in objects.items():
    uc.mem_write(obj + 8, b"\0")
    for rgb in rgbs:
        assert calibrate(profile, rgb) == rgb
        identity_checks += 1
    uc.mem_write(obj + 8, b"\1")
# Independently model the observed neutral path: integer percentage V then white scaling.
neutral_model_checks = 0
for _profile, rows in ramp.items():
    white = rows[-1]
    for i, actual in enumerate(rows):
        v = math.floor(i * 100 / 255 + 0.5)
        assert actual == [channel * v // 100 for channel in white]
        neutral_model_checks += 1
print(
    json.dumps(
        {
            "scope": (
                "Selected arithmetic instructions in Unicorn CPU emulator only; no DLL startup, "
                "vendor application, USB, network or Windows OS execution"
            ),
            "dll_sha256": hashlib.sha256(dll_bytes).hexdigest(),
            "profile_for_usb_strip_hardware_1_1": 2,
            "samples": results,
            "ramp_monotonic_per_channel": {
                p: all(
                    all(a <= b for a, b in zip(x, y, strict=True))
                    for x, y in zip(rows[:-1], rows[1:], strict=True)
                )
                for p, rows in ramp.items()
            },
            "neutral_ramp_black_outputs": {p: rows[0] for p, rows in ramp.items()},
            "neutral_ramp_white_outputs": {p: rows[-1] for p, rows in ramp.items()},
            "deterministic_random_rgb_samples_per_profile": 256,
            "repeated_random_outputs_exact": True,
            "disabled_calibration_identity_checks": identity_checks,
            "independent_neutral_model_checks": neutral_model_checks,
            "neutral_ramp_distinct_rgb_outputs": {
                p: len(set(map(tuple, rows))) for p, rows in ramp.items()
            },
            "math_import_calls": dict(counts),
            "unsupported_imports_executed": False,
            "limitation": (
                "Calibration is digital vendor behaviour, "
                "not a measured emitted-light colour reference. "
                "This emulator is not a Windows DLL compatibility test; synthetic math imports "
                "implement only finite ordinary values."
            ),
        },
        indent=2,
    )
)
