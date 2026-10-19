"""Read pinned images; emit aggregate block/cancellation evidence, never image bytes."""

import argparse
import collections
import hashlib
import itertools
import json
from pathlib import Path


def relations(rows):
    """GF(2) row dependencies, with a constant column excluding odd relations."""
    columns = {}
    pivots = {}
    dependencies = []
    for index, symbols in enumerate(rows):
        row = 1
        for symbol in symbols:
            column = columns.setdefault(symbol, len(columns) + 1)
            row ^= 1 << column
        terms = 1 << index
        while row:
            pivot = row.bit_length() - 1
            if pivot not in pivots:
                pivots[pivot] = row, terms
                break
            old_row, old_terms = pivots[pivot]
            row ^= old_row
            terms ^= old_terms
        if not row:
            dependencies.append(terms)
    return dependencies, len(columns)


def rank(values):
    pivots = {}
    for value in values:
        while value:
            pivot = value.bit_length() - 1
            if pivot not in pivots:
                pivots[pivot] = value
                break
            value ^= pivots[pivot]
    return len(pivots)


def controls():
    rectangle = [[(0, a), (1, b)] for a, b in [(1, 2), (1, 3), (4, 2), (4, 3)]]
    assert relations(rectangle)[0] == [0b1111]
    assert relations([[(0, 1)], [(0, 1)]])[0] == [0b11]
    assert relations([[(0, 1)], [(0, 2)]])[0] == []
    # Three rows cancel their symbols, but not the CRC's arbitrary constant term.
    assert relations([[1, 2], [2, 3], [3, 1]])[0] == []
    assert rank([0, 3, 7, 4, 3]) == 2
    return [
        "four_record_rectangle",
        "duplicate_pair",
        "independent_rows",
        "odd_relation_rejected",
        "binary_rank",
    ]


def analyse(root):
    pinned = (
        Path(__file__).parent.parent
        / "software-reverse-engineering-2026-10-15/firmware-hypotheses.json"
    )
    expected = json.loads(pinned.read_text())["images"]
    records = []
    images = []
    for entry in expected:
        image = root / (entry["version"] + ".firmware")
        if not image.is_file():
            raise ValueError("Expected regular local image")
        with image.open("rb") as source:
            raw = source.read(2 * 1024 * 1024 + 1)
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("Unexpected image hash: " + entry["version"])
        if len(raw) % 61:
            raise ValueError("Partial record")
        current = [raw[i : i + 61] for i in range(0, len(raw), 61)]
        records.extend(current)
        positions = collections.defaultdict(list)
        for record_index, record in enumerate(current):
            for position in range(7):
                positions[record[3 + 8 * position : 11 + 8 * position]].append(
                    (record_index, position)
                )
        pairs = [
            pair
            for locations in positions.values()
            for pair in itertools.combinations(locations, 2)
        ]
        images.append(
            {
                "version": entry["version"],
                "pairs": len(pairs),
                "same_record_different_position": sum(
                    a[0] == b[0] and a[1] != b[1] for a, b in pairs
                ),
                "different_record_position": sum(a[1] != b[1] for a, b in pairs),
                "different_full_record_data": sum(
                    current[a[0]][3:59] != current[b[0]][3:59] for a, b in pairs
                ),
                "nonfirst_unequal_predecessor": sum(
                    a[1] > 0
                    and b[1] > 0
                    and current[a[0]][3 + 8 * (a[1] - 1) : 3 + 8 * a[1]]
                    != current[b[0]][3 + 8 * (b[1] - 1) : 3 + 8 * b[1]]
                    for a, b in pairs
                ),
            }
        )
    rows = [[(p, r[3 + 8 * p : 11 + 8 * p]) for p in range(7)] for r in records]
    dependencies, columns = relations(rows)
    differences = []
    for terms in dependencies:
        header = trailer = 0
        for index, record in enumerate(records):
            if terms & (1 << index):
                header ^= int.from_bytes(record[:3], "big")
                trailer ^= int.from_bytes(record[59:], "big")
        differences.append((header, trailer))
    return {
        "scope": (
            "Conditional cancellation model: equal encoded blocks assumed to decode equally "
            "at each position across versions; CRC linear over decoded data and clear header"
        ),
        "positive_controls": controls(),
        "records": len(records),
        "symbol_position_columns": columns,
        "independent_even_record_relations": len(dependencies),
        "relation_term_histogram": dict(
            sorted(collections.Counter(t.bit_count() for t in dependencies).items())
        ),
        "independent_header_difference_rank": rank(h for h, _ in differences),
        "distinct_header_and_trailer_differences": [
            [f"{h:06x}", f"{t:04x}"] for h, t in sorted(set(differences))
        ],
        "block_position_analysis": images,
        "mcu_identified": False,
        "cipher_identified": False,
        "full_image_checksum_verified": False,
        "safe_to_flash": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="?", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps({"positive_controls": controls()}))
    elif args.images:
        print(json.dumps(analyse(args.images), indent=2))
    else:
        parser.error("Provide private image directory or --self-test")
