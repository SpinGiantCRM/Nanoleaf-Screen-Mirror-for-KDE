"""Offline protocol/clock regressions for the controlled USB trace decoder."""

import unittest

from step_response_trace import analyse, writes


def packet(data, timestamp):
    lines = []
    for index, offset in enumerate(range(0, len(data), 64)):
        report = b"\0" + data[offset : offset + 64]
        escaped = "".join(f"\\x{value:02x}" for value in report)
        lines.append(
            f'{timestamp + index / 100000:.6f} write(7, "{escaped}", {len(report)}) '
            f"= {len(report)} <0.000010>"
        )
    return "\n".join(lines)


def frame(code, timestamp):
    return packet(b"\x02\x00\x90" + bytes([code]) * 144, timestamp)


class TraceTests(unittest.TestCase):
    def test_complete_fragmented_frames_and_queries_are_distinguished(self):
        trace = packet(b"\x0c\0\0", 1000) + "\n" + frame(64, 1001)
        frames, lines = writes(trace, 48)
        self.assertEqual(lines, 4)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["mean_code"], 64)
        self.assertEqual(frames[0]["written_ns"], 1001000030000)

    def test_short_wrong_id_count_truncated_and_failed_writes_fail_closed(self):
        good = frame(64, 1000)
        for invalid in [
            good.replace("= 65", "= 64", 1),
            good.replace('"\\x00', '"\\x01', 1),
            good.rsplit("\n", 1)[0],
            good.replace("= 65", "= -1 EIO", 1),
        ]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                writes(invalid, 48)
        with self.assertRaises(ValueError):
            writes(good, 47)

    def test_known_steps_match_final_report_return_without_adding_ack_time(self):
        base = 1000
        requests = [
            {
                "unix_ns": (base + phase) * 1_000_000_000,
                "elapsed_ns": phase * 1_000_000_000,
                "requested_grey_code": 192 if phase % 2 else 64,
            }
            for phase in range(13)
        ]
        traces = [
            frame(192 if phase % 2 else 64, base + phase + n / 30 + 0.015)
            for phase in range(12)
            for n in range(30)
        ]
        traces.append(frame(0, base + 12))
        scene = {"step_paint_requests": requests}
        result = analyse("\n".join(traces), scene, 48, 360)
        self.assertGreaterEqual(result["matched_steps"], 6)
        self.assertEqual(result["distribution_ms"]["p95"], 15.03)
        with self.assertRaises(ValueError):
            analyse("\n".join(traces), scene, 48, 359)
        requests[5]["unix_ns"] += 3_000_000
        with self.assertRaises(ValueError):
            analyse("\n".join(traces), scene, 48, 360)


if __name__ == "__main__":
    unittest.main()
