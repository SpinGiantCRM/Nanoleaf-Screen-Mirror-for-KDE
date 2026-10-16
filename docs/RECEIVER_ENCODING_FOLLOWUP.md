# Receiver firmware encoding follow-up

16 October 2026. This follows the [earlier encoding research](FIRMWARE_ENCODING_FOLLOWUP.md)
and accompanies the [direct ACK experiments](USB_ACK_PATH_EXPERIMENTS.md).
No firmware command, loader entry, reset, erase, overclock or factory-data access
was performed. **There is still no safe firmware modification or flash procedure.**

## Stronger checksum constraints

The five pinned stock files contain 870 complete records and 4,837 distinct
eight-byte opaque symbols. Previously, each `(symbol, position)` was independent,
leaving eight candidate CRC polynomials. The new solver shares one unknown
16-bit decoded-block CRC for each symbol across positions. It advances that CRC
through subsequent bytes using a binary shift matrix, so its position-dependent
contribution is correct. Clear headers contribute separately. One common unknown
16-bit affine offset accounts for arbitrary initial/final constants at this fixed
record length.

This is conditional on identical encoded symbols decoding identically across
positions **and versions**, and on a reflected CRC over the clear header followed
by decoded bytes, stored big-endian. Those are hypotheses, not known properties
of the container.

The resulting system has 77,408 variables and 13,920 equations. Six earlier
polynomial candidates are inconsistent; **`a001` and `b876` remain consistent**,
each with rank 13,408. Both also remain consistent when the final eight-byte
symbol in the first file's first record is assumed to decode to zeros. That
extra assumption is unverified and is unnecessary for eliminating the six.

Consistency leaves more than 63,000 free binary variables. It does not establish
a unique polynomial, decoded bytes, CRC seed/XOR, cipher, key, instruction set,
MCU or valid firmware builder. Inconsistency excludes only the stated combined
model, not every possible interpretation of a stock file. Counts of inconsistent
reduced equations are not counts of independent checksum failures.

The public standard-library-only [solver and results](../perf/receiver-encoding-2026-10-16/README.md)
reproduce the analysis with private hash-pinned inputs. Controls verify the
CRC-16/ARC check vector, generated opaque-symbol records with nonzero initial
state/final XOR, rejection of one-bit corruption, a wrong polynomial and a false
zero-symbol assumption, and bounded input validation. No stock bytes or decoded
data are published by the tool.

## Finite cipher/key tests

Static data from the previously pinned Desktop 2.1.0, 2.2.4 and 3.0.1 releases was
read locally. Vendor JavaScript was never executed. Exact quoted ASCII/hex literals
of relevant lengths were considered as finite hypotheses, together with product
strings and common example/default derivations. Candidate literals and private
identifiers are excluded from public evidence.

| Test | Scope | Result |
| --- | --- | --- |
| Padding recognizer | 2,187 deduplicated default/product keys; DES/3DES, Blowfish, CAST5, IDEA, TEA and XTEA | No candidate |
| Vendor literals | 2,119 literal/example keys; 45,072 block operations, both transform directions | No candidate |
| Cross-record CRC | Union of 4,302 keys; standard 64-bit ciphers and TEA/XTEA with 8/16/32/64 cycles, block/key endian variants and both directions; both remaining polynomials | No three-record survivor |
| Corrected Block TEA | 1,563 128-bit keys, both directions and endian variants; independently on 8-byte blocks and whole 56-byte fields; all eight earlier polynomials | No three-record survivor |

The CRC tests compare the fixed-length checksum residual across three distinct
records. Any survivor would have been checked against all 870 records; **none
reached that stage**. This avoids treating guessed blank padding as necessary
plaintext. TEA/XTEA zero vectors, nonzero roundtrips, the CRC check vector and
Corrected Block TEA's zero vector/8-, 16- and 56-byte roundtrips passed.
The [authors' Corrected Block TEA paper](https://www.movable-type.co.uk/scripts/xxtea.pdf)
was used for the additional transform; this is not evidence that Nanoleaf uses it.

These tests exclude only the listed finite hypotheses and conditional checksum
layout. They are not exhaustive cryptanalysis and do not establish encryption.
More arbitrary dictionary guesses have no demonstrated route to recovering an
unknown 128-bit key. No opaque bytes were disassembled and presented as meaningful
machine code. Private script identities and sanitized counts are retained beside
the reproducible checksum analysis.

## Supported-command and recovery boundary

The [official historical protocol](https://nanoleaf.atlassian.net/wiki/pages/viewpage.action?pageId=2615574530&pageVersion=1)
links the `ch552_testing` demo and describes record decryption errors, but neither
identifies this retail controller's chip nor documents an independent recovery
route. The demo remains inaccessible in the attempted public fetches. Public
searches and the additional inspected independent driver yielded no supported
fast-strip command, firmware source, decoder or recovery procedure. Anonymous
guessed stock binary/map/HEX paths returned access-denied responses; these do
**not** prove those assets do not exist. No controller serial was sent in those
requests.

A fresh check of the existing support enquiry found only automated messages,
including its form confirmation, and no engineering answer. No new message was
sent. The exact MCU, accepted decoded image, factory-data layout and independent
closed-case recovery remain unknown. Stock update records are not full backups.

The receiver-side wait remains the leading explanation after the measured host
submission, pacing, brightness and packet-layout experiments failed to reduce it.
This is not proof of a particular internal UART, LED protocol, CPU clock or code
routine. Nor does an ACK timestamp identify the emitted-light instant.

Further material receiver gains now need new implementation evidence: a supported
faster command, manufacturer source/format details, or a validated decoder and
independent recovery method. A firmware modification is not ready to test. Entering
the loader to learn what happens would cross the user's no-flash/recovery boundary
without resolving it. No privileged USB access, driver detach or unknown feature
report was introduced as a substitute.

The daily native app/helper, full-frame fallback and previous immutable native
bundles are unchanged; mirroring is running. Configuration and calibration remain
byte-identical, and original controller power/brightness were restored with
readback. Python application retirement remains in effect. The new operator and
offline analysis tools are development tools, absent from the installed runtime.
