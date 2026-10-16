"""Offline, conditional CRC constraints for pinned stock files; never opens USB.

Equal opaque eight-byte symbols are assumed to decode identically, including
across positions and versions. The CRC is assumed reflected, over the clear
three-byte header followed by decoded data, with common initial/final constants.
Consistency does not prove any of those assumptions or recover plaintext.
"""

import argparse
import hashlib
import json
import random
from pathlib import Path


def crc(data, polynomial, state=0):
    for value in data:
        state ^= value
        for _ in range(8):
            state = (state >> 1) ^ (polynomial if state & 1 else 0)
    return state


def constraints(records, polynomial, zero_symbols=()):
    if not records or len(records) > 1024 or any(len(r) != 61 for r in records):
        raise ValueError("Expected 1..1024 complete 61-byte records")
    symbols = dict.fromkeys(r[3 + j : 11 + j] for r in records for j in range(0, 56, 8))
    symbols = {symbol: index for index, symbol in enumerate(symbols)}
    variable_count = (len(symbols) + 1) * 16
    rhs_bit = 1 << variable_count
    mask = rhs_bit - 1
    basis = {}
    inconsistent = equations = 0
    positions = []
    for position in range(7):
        # A symbol's CRC must advance through the following zero bytes. Each
        # output bit is a linear function of its 16 input bits, not a fresh
        # unknown for every (symbol, position).
        matrix = [crc(bytes(8 * (6 - position)), polynomial, 1 << bit) for bit in range(16)]
        positions.append(
            [sum(1 << k for k in range(16) if matrix[k] & (1 << out)) for out in range(16)]
        )

    def add(row):
        nonlocal inconsistent, equations
        equations += 1
        while coefficients := row & mask:
            pivot = coefficients.bit_length() - 1
            if pivot in basis:
                row ^= basis[pivot]
            else:
                basis[pivot] = row
                return
        inconsistent += bool(row & rhs_bit)

    for symbol in zero_symbols:
        if symbol in symbols:
            for bit in range(16):
                add(1 << (symbols[symbol] * 16 + bit))
    for record in records:
        observed = int.from_bytes(record[-2:], "big") ^ crc(record[:3] + bytes(56), polynomial)
        starts = [symbols[record[3 + p * 8 : 11 + p * 8]] * 16 for p in range(7)]
        for bit in range(16):
            # Fixed record length permits one shared unknown affine CRC
            # offset, covering arbitrary common initial state and final XOR.
            row = 1 << (len(symbols) * 16 + bit)
            if observed & (1 << bit):
                row |= rhs_bit
            for position, start in enumerate(starts):
                row ^= positions[position][bit] << start
            add(row)
    return {
        "polynomial": f"{polynomial:04x}",
        "symbols": len(symbols),
        "variables": variable_count,
        "equations": equations,
        "rank": len(basis),
        "inconsistent_equations": inconsistent,
        "consistent": inconsistent == 0,
    }


def controls():
    if crc(b"123456789", 0xA001) != 0xBB3D:
        raise AssertionError("CRC-16/ARC check vector failed")
    rng = random.Random(20261016)
    plain = [rng.randbytes(8) for _ in range(3)] + [bytes(8)]
    opaque = [hashlib.sha256(b"fixture" + p).digest()[:8] for p in plain]
    records = []
    for index in range(40):
        ids = [rng.randrange(4) for _ in range(7)]
        header = bytes([0x15]) + index.to_bytes(2, "big")
        decoded = b"".join(plain[j] for j in ids)
        encoded = b"".join(opaque[j] for j in ids)
        trailer = crc(header + decoded, 0xA001, 0x4237) ^ 0xA953
        records.append(header + encoded + trailer.to_bytes(2, "big"))
    if not constraints(records, 0xA001, [opaque[-1]])["consistent"]:
        raise AssertionError("Known generated CRC rejected")
    corrupt = records.copy()
    corrupt[4] = corrupt[4][:-1] + bytes([corrupt[4][-1] ^ 1])
    if constraints(corrupt, 0xA001, [opaque[-1]])["consistent"]:
        raise AssertionError("One-bit corruption accepted")
    if constraints(records, 0x8408, [opaque[-1]])["consistent"]:
        raise AssertionError("Wrong polynomial accepted")
    if constraints(records, 0xA001, [opaque[0], opaque[-1]])["consistent"]:
        raise AssertionError("False zero-symbol assumption accepted")
    for malformed in ([], [b"bad"], records * 26):
        try:
            constraints(malformed, 0xA001)
        except ValueError:
            continue
        raise AssertionError("Unbounded or malformed records accepted")
    return [
        "CRC-16/ARC check vector",
        "generated nonzero-seed/xor CRC accepted",
        "one-bit trailer corruption rejected",
        "wrong polynomial rejected",
        "incorrect zero-symbol assumption rejected",
        "malformed and excessive record counts rejected",
    ]


def analyse(root):
    pinned = (
        Path(__file__).parent.parent
        / "software-reverse-engineering-2026-10-15/firmware-hypotheses.json"
    )
    records = []
    for entry in json.loads(pinned.read_text())["images"]:
        path = root / (entry["version"] + ".firmware")
        if not path.is_file():
            raise ValueError("Expected regular local image")
        with path.open("rb") as source:
            raw = source.read(2 * 1024 * 1024 + 1)
        if hashlib.sha256(raw).hexdigest() != entry["sha256"] or len(raw) % 61:
            raise ValueError("Unexpected image hash or partial record")
        records.extend(raw[i : i + 61] for i in range(0, len(raw), 61))
    results = []
    # Reproduce both with no assumed plaintext and with the last block in the
    # first record assumed to decode to eight zero bytes. Neither is decryption.
    for polynomial in (0x07B1, 0x07E7, 0x0828, 0x27E4, 0x6000, 0x682D, 0xA001, 0xB876):
        for zero in ((), (records[0][-10:-2],)):
            result = constraints(records, polynomial, zero)
            result["first_tail_block_assumed_zero"] = bool(zero)
            results.append(result)
    return {
        "scope": __doc__,
        "controls": controls(),
        "records": len(records),
        "results": results,
        "plaintext_recovered": False,
        "mcu_identified": False,
        "safe_to_flash": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="?", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    # Operator tooling only; bound this dense elimination on the supported
    # Linux host. No third-party crypto package or application Python is needed.
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
    if args.self_test:
        print(json.dumps({"controls": controls()}))
    elif args.images:
        print(json.dumps(analyse(args.images), indent=2))
    else:
        parser.error("Provide private image directory or --self-test")
