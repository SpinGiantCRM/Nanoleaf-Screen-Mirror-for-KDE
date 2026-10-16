"""Synthetic, well-formed WCH comparison model; no USB or firmware inputs.

Models selected semantics of the published generic 2.31/2.40 disassembly, not
Nanoleaf firmware and not complete MCU/USB execution. Host-side bounds below
limit this model; they do not establish the loader's malformed-input behaviour.
No device adapter, command encoder, write, erase or loader-entry path exists.
"""

import hashlib
import json
import random
from dataclasses import dataclass


@dataclass
class ComparisonModel:
    memory: bytes
    hardened: bool
    mask: bytes
    latched: bool = False
    queries: int = 0

    def __post_init__(self):
        if len(self.memory) != 65536 or len(self.mask) != 8:
            raise ValueError("Synthetic memory must be 64 KiB; mask must be eight bytes")

    def compare(self, start, candidate):
        """Return semantic labels, not actual wire response bytes."""
        if (
            not 0 <= start < len(self.memory)
            or len(candidate) not in range(8, 57, 8)
            or start + len(candidate) > len(self.memory)
        ):
            raise ValueError("Outside the model's well-formed request scope")
        self.queries += 1
        if self.hardened:
            if start % 8 or start >= 0x3800:
                return "guard-rejected"
            if self.latched:
                return "latched"
        for index, value in enumerate(candidate):
            if (value ^ self.mask[index % 8]) != self.memory[start + index]:
                if self.hardened:
                    self.latched = True
                return "mismatch"
        return "match"


def synthetic_byte_walk(model, start, length, known_suffix):
    """Exercise an eight-byte equality oracle using a synthetic known boundary.

    Takes only a model, never a device callback. No plaintext is saved. A real
    loader, known mask, memory boundary and fresh independent entry are NOT
    established by a successful synthetic reconstruction.
    """
    if len(known_suffix) != 7 or not 1 <= length <= 1024:
        raise ValueError("Expected seven known suffix bytes and 1..1024 unknown bytes")
    recovered = known_suffix
    for address in range(start + length - 1, start - 1, -1):
        for guess in range(256):
            plain = bytes([guess]) + recovered[:7]
            encoded = bytes(value ^ model.mask[i] for i, value in enumerate(plain))
            result = model.compare(address, encoded)
            if result == "match":
                recovered = bytes([guess]) + recovered
                break
            if result != "mismatch":
                raise ValueError(f"Synthetic walk stopped: {result}")
        else:
            raise ValueError("Known boundary does not match synthetic memory")
    return recovered[:length]


def controls():
    rng = random.Random(29)
    memory = bytearray(rng.randbytes(65536))
    base, length = 0x2000, 64
    memory[base + length : base + length + 7] = bytes([255]) * 7
    memory = bytes(memory)
    mask = bytes(rng.randrange(256) for _ in range(8))
    original_hash = hashlib.sha256(memory).hexdigest()
    older = ComparisonModel(memory, False, mask)
    actual = synthetic_byte_walk(older, base, length, bytes([255]) * 7)
    assert actual == memory[base : base + length]

    wrong_boundary = ComparisonModel(memory, False, mask)
    try:
        synthetic_byte_walk(wrong_boundary, base, length, bytes(7))
    except ValueError as error:
        assert "boundary" in str(error)
    else:
        raise AssertionError("Unverified known boundary accepted")

    hardened = ComparisonModel(memory, True, mask)
    try:
        synthetic_byte_walk(hardened, base, length, bytes([255]) * 7)
    except ValueError as error:
        assert "guard-rejected" in str(error)
    else:
        raise AssertionError("Unaligned legacy walk accepted by hardened model")

    known = memory[base : base + 8]
    encoded = bytes(value ^ mask[i] for i, value in enumerate(known))
    bad = bytes([encoded[0] ^ 1]) + encoded[1:]
    assert hardened.compare(base, bad) == "mismatch"
    assert hardened.latched
    assert hardened.compare(base, encoded) == "latched"
    # A newly constructed MODEL represents a new initialized session. This is
    # not a reset implementation, transport reconnection or recovery procedure.
    restarted = ComparisonModel(memory, True, mask)
    assert restarted.compare(base, encoded) == "match"
    assert restarted.compare(0x3800, encoded) == "guard-rejected"

    # The inspected assembly guards only the START address, not the whole range.
    # Do not overstate that as a proven full-range loader read protection.
    crossing = memory[0x37F8 : 0x37F8 + 56]
    encoded_crossing = bytes(value ^ mask[i % 8] for i, value in enumerate(crossing))
    assert restarted.compare(0x37F8, encoded_crossing) == "match"
    for start, candidate in ((0, b"bad"), (-1, encoded), (65535, encoded)):
        try:
            restarted.compare(start, candidate)
        except ValueError:
            continue
        raise AssertionError("Out-of-model input accepted")
    assert hashlib.sha256(memory).hexdigest() == original_hash
    return {
        "scope": __doc__,
        "controls": [
            "legacy comparison reconstructs 64 synthetic bytes with known seven-byte suffix",
            "incorrect known suffix rejected",
            "hardened alignment blocks legacy byte walk",
            "first mismatch latches subsequent comparisons",
            "new initialized model clears latch; no hardware reset performed",
            "direct loader-region start rejected in hardened model",
            "start-only guard permits bounded range crossing in this model",
            "out-of-model request shapes rejected",
            "synthetic memory remains byte-identical",
        ],
        "legacy_synthetic_queries": older.queries,
        "legacy_unknown_bytes": length,
        "maximum_guesses_per_byte_under_old_oracle_assumptions": 256,
        "unconstrained_eight_byte_block_possibilities": str(256**8),
        "timing_or_device_measurement": False,
        "dongle_backup_or_recovery_verified": False,
    }


if __name__ == "__main__":
    print(json.dumps(controls(), indent=2))
