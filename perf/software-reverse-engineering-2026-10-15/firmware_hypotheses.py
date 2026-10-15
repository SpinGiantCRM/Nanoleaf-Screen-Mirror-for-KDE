import argparse
import collections
import hashlib
import json
import math
from pathlib import Path

parser = argparse.ArgumentParser(
    description="Offline firmware hypotheses; no decryption, device access or writes"
)
parser.add_argument(
    "images", type=Path, help="Directory containing private 1.1.0 through 1.5.0 .firmware files"
)
ROOT = parser.parse_args().images
EXPECTED = {
    row["version"]: row["sha256"]
    for row in json.loads((Path(__file__).parent / "firmware-hypotheses.json").read_text())[
        "images"
    ]
}


def entropy(data):
    return (
        -sum((n / len(data)) * math.log2(n / len(data)) for n in collections.Counter(data).values())
        if data
        else 0
    )


TOKENS = [x.encode("utf-16le") for x in ["Nanoleaf", "NL82K2", "NLUSB-BL", "NanoGrid"]]


def probes(data):
    matches = []
    for token in TOKENS:
        for period in [1, 2, 4, 8]:
            if len(token) < period + 4:
                continue
            for offset in range(len(data) - len(token) + 1):
                delta = bytes(
                    a ^ b for a, b in zip(data[offset : offset + len(token)], token, strict=True)
                )
                if all(delta[i] == delta[i % period] for i in range(period, len(delta))):
                    matches.append(
                        {
                            "token_utf16": token.decode("utf-16le"),
                            "period": period,
                            "offset": offset,
                        }
                    )
    return matches


# Positive controls test every searched period, non-zero phase and arbitrary keys.
controls = []
for period in [1, 2, 4, 8]:
    plain = b"abc" + TOKENS[0] + b"xyz"
    key = bytes(range(9, 9 + period))
    coded = bytes(v ^ key[i % period] for i, v in enumerate(plain))
    assert any(
        m["period"] == period and m["offset"] == 3 and m["token_utf16"] == "Nanoleaf"
        for m in probes(coded)
    )
    controls.append(period)
results = []
payloads = []
for version in ["1.1.0", "1.2.0", "1.3.0", "1.4.0", "1.5.0"]:
    image = ROOT / (version + ".firmware")
    if not image.is_file():
        raise SystemExit("Input must be a regular local file: " + version)
    with image.open("rb") as source:
        raw = source.read(2 * 1024 * 1024 + 1)
    if hashlib.sha256(raw).hexdigest() != EXPECTED[version]:
        raise SystemExit("Refusing image with unexpected SHA-256: " + version)
    data = b"".join(raw[i + 3 : i + 59] for i in range(0, len(raw), 61))
    payloads.append(data)
    results.append(
        {
            "version": version,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "data_bytes": len(data),
            "phase_8_entropy_bits_per_byte": [entropy(data[i::8]) for i in range(8)],
            "known_utf16_repeating_xor_matches": probes(data),
        }
    )
comparisons = []
for i in range(4):
    a, b = payloads[i : i + 2]
    dist = [
        sum((x ^ y).bit_count() for x, y in zip(a[j : j + 8], b[j : j + 8], strict=True))
        for j in range(0, min(len(a), len(b)), 8)
        if a[j : j + 8] != b[j : j + 8]
    ]
    comparisons.append(
        {
            "a": results[i]["version"],
            "b": results[i + 1]["version"],
            "changed_same_offset_8_byte_blocks": len(dist),
            "mean_changed_block_hamming_distance_bits": sum(dist) / len(dist),
            "minimum_changed_block_hamming_distance_bits": min(dist),
            "maximum_changed_block_hamming_distance_bits": max(dist),
        }
    )
print(
    json.dumps(
        {
            "scope": (
                "Offline bounded hypotheses; no decryption, CPU identity or flash-safety conclusion"
            ),
            "positive_control_periods": controls,
            "images": results,
            "comparisons": comparisons,
            "limitation": (
                "No match only excludes these known UTF-16 strings under the tested aligned "
                "periodic XOR hypotheses. Missing strings or other encodings remain possible. "
                "XOR preserves each phase entropy but entropy alone does not identify encryption."
            ),
            "mcu_identified": False,
            "cipher_identified": False,
            "safe_to_flash": False,
        },
        indent=2,
    )
)
