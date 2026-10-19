"""Bounded offline encoding hypotheses; no USB, network or firmware writer.

CRC models are conditional on the clear header followed by 56 decoded bytes,
big-endian trailers and common initial/final constants. Equal encoded blocks
alone do not establish that model or a particular cipher/CPU.
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


def validate_records(records):
    if not records or len(records) > 1024 or any(len(r) != 61 for r in records):
        raise ValueError("Expected 1..1024 complete 61-byte records")


def solve_model(records, polynomial, period=1, linear=False):
    """Reject a model at its first inconsistent binary equation, if any.

    Byte models permit arbitrary, possibly non-bijective substitutions per byte
    position modulo period. Linear models permit an arbitrary affine 64-bit
    block transform: its decoded-block CRC is an unknown affine 16x64 mapping.
    Neither model outputs plaintext or a substitution table.
    """
    validate_records(records)
    if period not in (1, 2, 4, 8) or not 0 < polynomial <= 0xFFFF:
        raise ValueError("Unsupported period or polynomial")
    keys = (
        list(range(64))
        if linear
        else sorted({(p % period, r[3 + p]) for r in records for p in range(56)})
    )
    indices = {key: index for index, key in enumerate(keys)}
    variables = len(keys) * (16 if linear else 8) + 16
    rhs_bit = 1 << variables
    mask = rhs_bit - 1
    basis = {}
    positions = []
    for position in range(7 if linear else 56):
        vectors = [
            crc(bytes(8 * (6 - position)), polynomial, 1 << bit)
            if linear
            else crc(bytes([1 << bit]) + bytes(55 - position), polynomial)
            for bit in range(16 if linear else 8)
        ]
        positions.append(
            [
                sum(1 << bit for bit, value in enumerate(vectors) if value & (1 << out))
                for out in range(16)
            ]
        )
    examined = 0
    for record in records:
        observed = int.from_bytes(record[-2:], "big") ^ crc(record[:3] + bytes(56), polynomial)
        for bit in range(16):
            examined += 1
            row = 1 << (variables - 16 + bit)  # common affine CRC offset
            if observed & (1 << bit):
                row |= rhs_bit
            if linear:
                for position in range(7):
                    block = int.from_bytes(record[3 + 8 * position : 11 + 8 * position], "little")
                    while block:
                        index = (block & -block).bit_length() - 1
                        row ^= positions[position][bit] << (index * 16)
                        block &= block - 1
            else:
                for position in range(56):
                    start = indices[(position % period, record[3 + position])] * 8
                    row ^= positions[position][bit] << start
            while coefficients := row & mask:
                pivot = coefficients.bit_length() - 1
                if pivot in basis:
                    row ^= basis[pivot]
                else:
                    basis[pivot] = row
                    break
            else:
                if row & rhs_bit:
                    return model_result(
                        polynomial, period, linear, variables, examined, basis, False
                    )
    return model_result(polynomial, period, linear, variables, examined, basis, True)


def model_result(polynomial, period, linear, variables, examined, basis, consistent):
    return {
        "polynomial": f"{polynomial:04x}",
        "model": "affine-64-bit-block" if linear else f"bytewise-period-{period}",
        "variables": variables,
        "equations_examined": examined,
        "rank": len(basis),
        "consistent": consistent,
    }


def whole_affine(records):
    """Test any shared affine mapping from all stored header/data bits to CRC.

    This does not assume a CRC polynomial or decoded byte order. It does assume
    one fixed affine mapping across the supplied versions, with a constant term.
    """
    validate_records(records)
    basis = {}
    contradiction = None
    for index, record in enumerate(records):
        row = int.from_bytes(record[:59], "big") | (1 << (59 * 8))
        rhs = int.from_bytes(record[-2:], "big")
        while row:
            pivot = row.bit_length() - 1
            if pivot in basis:
                old, old_rhs = basis[pivot]
                row ^= old
                rhs ^= old_rhs
            else:
                basis[pivot] = row, rhs
                break
        else:
            if rhs:
                contradiction = index
                break
    return {
        "records_available": len(records),
        "first_contradiction_record_ordinal": contradiction,
        "rank": len(basis),
        "consistent": contradiction is None,
    }


def load_images(root):
    pins = (
        Path(__file__).parent.parent
        / "software-reverse-engineering-2026-10-15/firmware-hypotheses.json"
    )
    images = []
    for entry in json.loads(pins.read_text())["images"]:
        path = root / (entry["version"] + ".firmware")
        if not path.is_file():
            raise ValueError("Expected regular local image")
        with path.open("rb") as source:
            raw = source.read(2 * 1024 * 1024 + 1)
        if hashlib.sha256(raw).hexdigest() != entry["sha256"] or len(raw) % 61:
            raise ValueError("Unexpected image hash or partial record")
        images.append((entry["version"], [raw[i : i + 61] for i in range(0, len(raw), 61)]))
    return images


def controls():
    if crc(b"123456789", 0xA001) != 0xBB3D:
        raise AssertionError("CRC check vector failed")
    rng = random.Random(42)
    tables = []
    for _ in range(8):
        table = list(range(256))
        rng.shuffle(table)
        tables.append(table)
    fixtures = []
    for index in range(200):
        header = bytes([0x15]) + index.to_bytes(2, "big")
        encoded = bytes(rng.randrange(8) for _ in range(56))
        plain = bytes(tables[p % 8][v] for p, v in enumerate(encoded))
        trailer = crc(header + plain, 0xA001, 0x4237) ^ 0xA953
        fixtures.append(header + encoded + trailer.to_bytes(2, "big"))
    if not solve_model(fixtures, 0xA001, 8)["consistent"]:
        raise AssertionError("Generated nonlinear substitution rejected")
    bad = fixtures.copy()
    bad[3] = bad[3][:-1] + bytes([bad[3][-1] ^ 1])
    if solve_model(bad, 0xA001, 8)["consistent"]:
        raise AssertionError("Corrupt substitution accepted")
    if solve_model(fixtures, 0xA001, 1)["consistent"]:
        raise AssertionError("Wrong period accepted")
    if solve_model(fixtures, 0x8408, 8)["consistent"]:
        raise AssertionError("Wrong polynomial accepted")
    # Exercise every supported repetition period with both conditional CRCs,
    # using a table-free CRC to construct the synthetic observations.
    for polynomial in (0xA001, 0xB876):
        for period in (1, 2, 4, 8):
            generated = []
            for index in range(80):
                header = bytes([0x15]) + index.to_bytes(2, "big")
                encoded = bytes(rng.randrange(4) for _ in range(56))
                plain = bytes(tables[p % period][v] for p, v in enumerate(encoded))
                trailer = crc(header + plain, polynomial, 0x4237) ^ 0xA953
                generated.append(header + encoded + trailer.to_bytes(2, "big"))
            if not solve_model(generated, polynomial, period)["consistent"]:
                raise AssertionError("Supported period/polynomial rejected")
    matrix = [rng.getrandbits(64) for _ in range(64)]
    constant = rng.getrandbits(64)
    affine = []
    for index in range(200):
        header = bytes([0x15]) + index.to_bytes(2, "big")
        data = rng.randbytes(56)
        plain = bytearray()
        for position in range(7):
            block = int.from_bytes(data[8 * position : 8 * position + 8], "little")
            value = constant
            while block:
                bit = (block & -block).bit_length() - 1
                value ^= matrix[bit]
                block &= block - 1
            plain.extend(value.to_bytes(8, "little"))
        trailer = crc(header + plain, 0xA001, 0x4237) ^ 0xA953
        affine.append(header + data + trailer.to_bytes(2, "big"))
    if not solve_model(affine, 0xA001, linear=True)["consistent"]:
        raise AssertionError("Generated cross-byte affine transform rejected")
    bad = affine.copy()
    bad[3] = bad[3][:-1] + bytes([bad[3][-1] ^ 1])
    if solve_model(bad, 0xA001, linear=True)["consistent"]:
        raise AssertionError("Corrupt affine transform accepted")
    # More than 473 independent input bits/constant columns are needed to
    # challenge an arbitrary whole-field affine mapping; 200 random rows alone
    # could fit an arbitrary output, including a corruption.
    whole_matrix = [rng.getrandbits(16) for _ in range(59 * 8)]
    whole_constant = rng.getrandbits(16)
    whole = []
    for _ in range(600):
        data = rng.randbytes(59)
        bits = int.from_bytes(data, "big")
        value = whole_constant
        while bits:
            bit = (bits & -bits).bit_length() - 1
            value ^= whole_matrix[bit]
            bits &= bits - 1
        whole.append(data + value.to_bytes(2, "big"))
    bad_whole = whole.copy()
    bad_whole[-1] = bad_whole[-1][:-1] + bytes([bad_whole[-1][-1] ^ 1])
    if not whole_affine(whole)["consistent"] or whole_affine(bad_whole)["consistent"]:
        raise AssertionError("Whole-field affine controls failed")
    for malformed in ([], [b"bad"], fixtures * 6):
        for function in (whole_affine, lambda rows: solve_model(rows, 0xA001)):
            try:
                function(malformed)
            except ValueError:
                continue
            raise AssertionError("Invalid record count/shape accepted")
    return [
        "CRC check vector",
        "generated nonlinear period-8 substitution accepted",
        "one-bit substitution corruption rejected",
        "wrong period and polynomial rejected",
        "all supported periods accepted for both candidate polynomials",
        "generated cross-byte affine transform accepted",
        "one-bit affine corruption rejected",
        "whole-field affine positive and corruption controls",
        "malformed and excessive records rejected",
    ]


def analyse(root):
    images = load_images(root)
    records = [record for _, rows in images for record in rows]
    results = []
    for polynomial in (0xA001, 0xB876):
        for period in (1, 2, 4, 8):
            results.append(solve_model(records, polynomial, period))
        results.append(solve_model(records, polynomial, linear=True))
    return {
        "scope": __doc__,
        "records": len(records),
        "models": results,
        "whole_stored_field_affine": whole_affine(records),
        "plaintext_recovered": False,
        "mcu_identified": False,
        "safe_to_flash": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="?", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
    if args.self_test:
        print(json.dumps({"controls": controls()}))
    elif args.images:
        print(json.dumps(analyse(args.images), indent=2))
    else:
        parser.error("Provide private image directory or --self-test")
