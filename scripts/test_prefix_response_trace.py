"""Independent generated protocol/retention/ACK-clock regressions."""

import unittest

from prefix_response_trace import analyse, frames
from test_step_response_trace import packet


def ack(when):
    return f'{when:.6f} read(7, "\\x82\\x00\\x01\\x00", 1024) = 4 <0.000010>'


def scene(fractional=False):
    events = [
        {
            "unix_ns": 1_000_000_000_000 + i * 200_000_000,
            "monotonic_ns": i * 200_000_000,
            "high": i % 2,
        }
        for i in range(51)
    ]
    lines = []
    for index in range(200):
        code = 64 if index // 4 % 2 else 8
        raw = bytearray([code] * 36 + [8] * 108)
        if fractional:
            raw[-3:] = bytes([round(8.25 + (((index + 141) % 8 + 0.5) / 8 - 0.5))]) * 3
        if index > 0 and not fractional:
            raw = raw[:36]
        when = 1000 + index / 20
        lines.append(packet(b"\x02" + len(raw).to_bytes(2, "big") + raw, when + 0.005))
        lines.append(ack(when + 0.008))
    lines.append(packet(b"\x02\x00\x90" + bytes(144), 1010))
    lines.append(ack(1010.003))
    return "\n".join(lines), events


class PrefixTraceTests(unittest.TestCase):
    def test_source_to_write_and_ack_are_separate_with_exact_retained_state(self):
        text, events = scene()
        result = analyse(text, events, "integer", 200)
        self.assertEqual(result["event_to_write_ms"]["median"], 5.01)
        self.assertEqual(result["event_to_ack_ms"]["median"], 8.01)
        self.assertEqual(result["shortened_transactions"], 199)
        self.assertTrue(result["all_frame_acks_traced"])
        self.assertEqual(result["full_state_exact_comparisons"], 200)

    def test_missing_extra_failed_ack_and_uninitialised_state_fail_closed(self):
        text, events = scene()
        first = text.index("\n", text.index("read("))
        invalid = [
            text[: text.index("read(") - len("1000.008000 ")] + text[first + 1 :],
            text + "\n" + ack(1010.004),
            text.replace('"\\x82\\x00\\x01\\x00"', '"\\x82\\x00\\x01\\x01"', 1),
        ]
        for value in invalid:
            with self.subTest(value=value[-100:]), self.assertRaises(ValueError):
                analyse(value, events, "integer", 200)
        with self.assertRaises(ValueError):
            frames(packet(b"\x02\x00\x24" + bytes([8]) * 36, 1000), 48)

    def test_fractional_phase_corruption_and_clock_drift_are_rejected(self):
        text, events = scene(True)
        result = analyse(text, events, "fractional", 200)
        self.assertEqual(result["full_state_exact_comparisons"], 200)
        # The second full frame needs tail9; corruption freezes it at8.
        bad = text.replace("\\x09\\x09\\x09", "\\x08\\x08\\x08", 1)
        with self.assertRaisesRegex(ValueError, "fractional"):
            analyse(bad, events, "fractional", 200)
        events[5]["unix_ns"] += 3_000_000
        with self.assertRaisesRegex(ValueError, "drift"):
            analyse(text, events, "fractional", 200)


if __name__ == "__main__":
    unittest.main()
