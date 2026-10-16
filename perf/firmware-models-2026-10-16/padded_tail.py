"""Test uniform-tail arithmetic encodings offline; never save decoded firmware.

Conditional on the final repeated eight-byte block decoding to one repeated
byte. Any first-stage survivor must also match every record's CRC residual.
Even that would not verify executable code, chip identity or recovery.
"""

import argparse
import json
import random

from analyse_models import crc, load_images, validate_records

TABLES = {p: [crc(bytes([v]), p) for v in range(256)] for p in (0xA001, 0xB876)}
BYTE_ORDER_MASKS = tuple(range(8))


def fast_crc(data, polynomial):
    state = 0
    table = TABLES[polynomial]
    for value in data:
        state = (state >> 8) ^ table[(state ^ value) & 255]
    return state


def transform(data, tail, width, order, operation, fill):
    output = bytearray()
    mask = (1 << (8 * width)) - 1
    constant = int.from_bytes(bytes([fill]) * width, order)
    for position in range(0, len(data), width):
        encoded = int.from_bytes(data[position : position + width], order)
        terminal = int.from_bytes(tail[position % 8 : position % 8 + width], order)
        if operation == "xor":
            value = encoded ^ terminal ^ constant
        elif operation == "add":
            value = encoded + constant - terminal
        else:
            value = constant + terminal - encoded
        output.extend((value & mask).to_bytes(width, order))
    return bytes(output)


def permute(data, mask):
    return bytes(data[p + (i ^ mask)] for p in range(0, len(data), 8) for i in range(8))


def search(records, masks=BYTE_ORDER_MASKS):
    validate_records(records)
    if len(records) < 4:
        raise ValueError("Need at least three interior records and one terminal record")
    tail = records[-1][3:11]
    if records[-1][3:59] != tail * 7:
        raise ValueError("Terminal record is not one repeated eight-byte block")
    selected = [records[i] for i in (16, 64, 128)] if len(records) > 128 else records[:3]
    hits = []
    count = 0
    for width in (1, 2, 4, 8):
        for order in ("little",) if width == 1 else ("little", "big"):
            for operation in ("xor", "add", "subtract"):
                for fill in range(256):
                    count += 1
                    decoded = [
                        transform(record[3:59], tail, width, order, operation, fill)
                        for record in selected
                    ]
                    for permutation in masks:
                        data = [permute(value, permutation) for value in decoded]
                        for header_order in ("big", "little"):
                            for polynomial in (0xA001, 0xB876):
                                residues = []
                                for record, value in zip(selected, data, strict=True):
                                    header = (
                                        record[:3]
                                        if header_order == "big"
                                        else record[:1] + record[1:3][::-1]
                                    )
                                    residues.append(
                                        fast_crc(header + value, polynomial)
                                        ^ int.from_bytes(record[-2:], "big")
                                    )
                                    if residues[-1] != residues[0]:
                                        break
                                if len(residues) != len(selected) or len(set(residues)) != 1:
                                    continue
                                good = 0
                                for record in records:
                                    header = (
                                        record[:3]
                                        if header_order == "big"
                                        else record[:1] + record[1:3][::-1]
                                    )
                                    value = permute(
                                        transform(
                                            record[3:59], tail, width, order, operation, fill
                                        ),
                                        permutation,
                                    )
                                    good += (
                                        fast_crc(header + value, polynomial)
                                        ^ int.from_bytes(record[-2:], "big")
                                        == residues[0]
                                    )
                                hits.append(
                                    {
                                        "word_bytes": width,
                                        "word_order": order,
                                        "operation": operation,
                                        "assumed_uniform_tail_byte": fill,
                                        "output_permutation_mask": permutation,
                                        "header_index_order": header_order,
                                        "polynomial": f"{polynomial:04x}",
                                        "matching_full_corpus_records": good,
                                        "full_corpus_records": len(records),
                                    }
                                )
    return {
        "transform_candidates_including_redundant_representations": count,
        "output_permutations": len(masks),
        "survivors": hits,
    }


def controls():
    if fast_crc(b"123456789", 0xA001) != 0xBB3D:
        raise AssertionError("CRC check vector failed")
    rng = random.Random(42)
    keys = (0x1234, 0x5678, 0x90AB, 0xCDEF)
    records = []
    for index in range(5):
        header = bytes([0x15]) + index.to_bytes(2, "big")
        plain = bytes([255]) * 56 if index == 4 else rng.randbytes(56)
        encoded = b"".join(
            ((int.from_bytes(plain[j : j + 2], "little") - keys[(j % 8) // 2]) & 65535).to_bytes(
                2, "little"
            )
            for j in range(0, 56, 2)
        )
        # Independent table-free CRC and arbitrary common initial/final constants.
        trailer = crc(header + plain, 0xA001, 0x4237) ^ 0xA953
        records.append(header + encoded + trailer.to_bytes(2, "big"))
    result = search(records, range(1))
    if not any(
        hit["operation"] == "add"
        and hit["word_bytes"] == 2
        and hit["word_order"] == "little"
        and hit["assumed_uniform_tail_byte"] == 255
        and hit["matching_full_corpus_records"] == len(records)
        for hit in result["survivors"]
    ):
        raise AssertionError("Generated additive decoder was not recovered")
    bad = records.copy()
    bad[-1] = bad[-1][:-1] + bytes([bad[-1][-1] ^ 1])
    if any(
        hit["matching_full_corpus_records"] == len(bad)
        for hit in search(bad, range(1))["survivors"]
    ):
        raise AssertionError("Corruption admitted as complete-image match")
    bad_tail = records.copy()
    bad_tail[-1] = bytes(3) + bytes(range(56)) + bytes(2)
    for malformed in (records[:1], [b"bad"], bad_tail):
        try:
            search(malformed)
        except ValueError:
            continue
        raise AssertionError("Malformed/nonrepeating tail accepted")
    return [
        "CRC check vector",
        "unknown generated additive decoder recovered",
        "nonzero CRC initial/final constants retained",
        "corrupt trailer cannot become a complete-image match",
        "short, malformed and nonrepeating-tail inputs rejected",
    ]


if __name__ == "__main__":
    import resource
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="?", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    if args.self_test:
        print(json.dumps({"controls": controls()}))
    elif args.images:
        records = dict(load_images(args.images))["1.5.0"]
        print(
            json.dumps(
                {
                    "scope": __doc__,
                    "records": len(records),
                    "result": search(records),
                    "plaintext_recovered": False,
                    "safe_to_flash": False,
                },
                indent=2,
            )
        )
    else:
        parser.error("Provide private image directory or --self-test")
