# Firmware decoding and independent recovery follow-up

16 October 2026. Continues the [receiver encoding analysis](RECEIVER_ENCODING_FOLLOWUP.md)
and [closed-case recovery investigation](CUSTOM_FIRMWARE_RECOVERY.md).

Latest: [WCH verification restrictions and closed-case backup assessment](WCH_BACKUP_RECOVERY.md),
including later 2025 evidence and a synthetic comparison model.

**The chip remains unconfirmed, the stock payload has not been decoded, and no
independent closed-case recovery method has been established. Nothing was flashed
or sent to USB for this investigation.** The installed native application,
calibration and retained native rollback bundles are unchanged.

## Chip identification: stronger product provenance, same silicon uncertainty

The official [product declarations catalogue](https://nanoleaf.me/en-gb/pages/product-declarations)
links an [NL82K22 declaration](https://nanoleaf.box.com/shared/static/qgefwejpxdg831flerpx6p53uchmtdtc.pdf),
signed 20 May 2025. It identifies SKU `N7601K00-1LS4D`, PC Screen Mirror and
5 V / 2 A, matching the product family on the exterior label. The two-page PDF
contains no MCU, board diagram, bill of materials or loader/recovery procedure.
Its hash is retained with the source metadata.

The historical vendor `nanoleaf/ch552_testing` demo remains the strongest CH552
lead. That name, the retail runtime identity and USB endpoint sizes do not prove
the production chip, package or factory-loader configuration. No internal image
or board-specific source was found in the additional public searches.

Exact-origin Software Heritage lookups returned 404; the Wayback index query
returned an empty result. Additional current Common Crawl indexes returned
404 or 503, and one Software Heritage search met a bot challenge. These are
coverage limits, not proof the source was never archived. An initial query used
an unavailable Common Crawl index and contributes no evidence of absence.
Public vendor-wiki searches found the known USB page in positive controls but no
additional current CH552/loader page. A current index need not cover historical
revisions. GitHub search was likewise incomplete, including for known sources.

## Stock decoding: actual new offline tests

The five pinned versions 1.1.0–1.5.0 still total 870 records. The model tests below
are implemented in two bounded, standard-library-only scripts with generated
positive and corruption controls. Source, reproduction commands and numerical
results are in [the evidence directory](../perf/firmware-models-2026-10-16/README.md).
Private finite searches and inconclusive solver attempts are labelled separately.

### Shared substitution and affine models

As before, CRC-based exclusions assume the clear three-byte header followed by
56 decoded data bytes, a big-endian stored trailer, one common CRC initial/final
offset and a transform shared across versions. Wrong assumptions can invalidate
the exclusions. `a001` and `b876` are conditional polynomial candidates, not
validated CRC identities.

| Proposed decoding model | Result for both remaining polynomials |
| --- | --- |
| Arbitrary byte substitution repeated every 1, 2 or 4 positions | Inconsistent |
| Arbitrary byte substitution repeated every 8 positions | Consistent but underdetermined |
| Arbitrary affine transform shared by all 64-bit blocks | Inconsistent |

The period-8 model has 16,400 variables and rank 13,408 after 13,920 equations:
2,992 binary degrees of freedom remain. It permits non-bijective byte tables,
so a fit does not prove a valid substitution cipher, let alone recover code.
The bytewise models map each stored byte through its position's table; they do
not encompass arbitrary cross-byte nonlinear mixing or permutation.
The affine-block model represents its decoded-block CRC as an arbitrary
16-by-64 binary map plus a common offset, encompassing cross-byte linear mixing.
It fails at equation 1,042 with rank 1,040 for either candidate polynomial.

A separate polynomial-independent check asks whether **any one affine map from
all 59 stored header/data bytes to the 16-bit trailer** fits all files. It fails
on the 485th examined record, with rank 459. This rejects that shared affine
relationship; it does not reject nonlinear, version-specific or differently
structured encodings. Merely swapping the clear index's byte order in the older
shared-symbol CRC solver leaves both candidate polynomials consistent. Endian
ambiguity is unresolved.

### Wider finite cipher search

A private follow-up used 4,317 finite candidate byte strings: the previous union
plus 15 initial-data-field candidates of 8/16/24 bytes. Key-length requirements
produce **48,628 decoder candidates**, not an exhaustive key space. Tests covered
DES/3DES, Blowfish, CAST5, IDEA and 32-cycle TEA/XTEA, both directions, supported
block/key word orders, eight output byte permutations, two clear-index byte
orders and the two remaining CRC candidates.

Selection used interior 1.5.0 records 16, 64 and 128, avoiding an assumption that
the initial record is ordinary executable code. **No candidate matched all three
CRC residuals**, so none reached complete-image validation. Key guesses,
proprietary source and decoded bytes are not published. These are negative finite
hypotheses, not a cryptographic proof against those algorithms.

### The repeated terminal block

Every data block in the final 1.5.0 record is the same eight-byte symbol. If it
represents a uniform plaintext padding byte, an eight-byte repeating XOR or
wordwise arithmetic constant can be derived without guessing that constant.

The new public search tried every uniform byte 0–255, word widths 1/2/4/8,
little/big-endian words, XOR and both subtraction directions, eight common
output permutations, both clear-index orders and both CRC candidates. Its
**5,376 transform representations include redundant cases**. No three-interior-
record survivor emerged; any survivor would have been checked against all 171
records. The generated positive control recovers an unknown additive transform;
a damaged terminal trailer cannot pass the complete-image check.

This excludes the listed uniform-tail hypotheses only. The repeated symbol could
decode to nonuniform bytes or represent metadata rather than padding.

Across all versions, data-relative blocks at `0x10` through `0x40`, stepping by
eight, also repeat. These are equality observations, not an identified interrupt
table. No disassembly of opaque bytes is presented as chip identification.

### Attempts that did not resolve anything

Bounded Z3 searches for unknown repeating byte-add and 64-bit word-add transforms
returned **UNKNOWN/timeouts in all 12 stock cases**, eight seconds each. A
supplied-key synthetic control passed and its corruption was rejected, but an
earlier unknown-key positive control also timed out. An independent native-XOR
SAT formulation timed out on its unknown-key synthetic control after about
16 seconds and was stopped before stock tests. These outcomes do not exclude
addition models. Solver packages live only in private analysis environments;
neither the application nor CI gains a solver/crypto dependency.

## Recovery: distinguish three separate mechanisms

### Nanoleaf's vendor updater

The previously inspected updater handles an already-enumerated `NLUSB-BL`,
performs destructive update operations and restarts the application. It gives us
a stock update asset and a vendor update protocol. It still provides no proven
entry path when the application cannot run and no full factory-data backup.

This follow-up inspected 17 additional GUI/translation archive members, checking
their recorded integrity hashes. The apparent recovery labels do not supply the
missing route: power-loss recovery is an output behaviour setting, five-second
button instructions concern other networked products, shared DFU UI code is not
an NL82 independent entry procedure, and the backend reboot-recovery symbol is
in network security code. Current PC Screen Mirror manuals add no demonstrated
dead-application recovery procedure. No vendor code was executed.

### WCH factory ISP, conditional on actual hardware

The manufacturer-authored [CH552 datasheet](https://cdn-learn.adafruit.com/assets/assets/000/129/847/original/CH552DS1.PDF)
describes flash-resident loader/startup and read-protection settings. The official
[CH55x ISP presentation](https://www.wch.cn/uploads/file/20190813/1565677668885919.pdf)
also shows application-triggered loader entry. Neither establishes this retail
unit's chip, retained loader, startup configuration or an independent closed-case
entry route. An application jump is not recovery from a broken application.

Static inspection of pinned [librech551 source](https://raw.githubusercontent.com/rgwan/librech551/fb2779c5e82280d56ecf39b14558ee31bf68b053/usbisp/main.c)
distinguishes WCH's factory ISP from Nanoleaf HID: its device identity and bulk
transport differ. Its data-flash read is a small separate region, not complete
code/loader readback. Its programming path erases code before writing, and its
v2 path rejects the data-flash read option. No program was compiled or run.

The pinned chprog [v1](https://raw.githubusercontent.com/ole00/chprog/423612b053e79d174180a58aee6259e4c112d622/prot_v1.c)
and [v2](https://raw.githubusercontent.com/ole00/chprog/423612b053e79d174180a58aee6259e4c112d622/prot_v2.c)
sources likewise separate detection, verification and writes. A function name
such as “detect” is not a universal guarantee of no state changes: the v1
routine also sets a session key. The v2 write path sends a configuration/init
packet before erase/write. Generic tools must not be tried casually on an
unidentified retail controller or fed Nanoleaf's opaque container.

### Possible verification-oracle backup lead

The [2019 CH55x research thread](https://www.mikrocontroller.net/topic/462538?page=single)
contains first-person reports of extracting loader contents using repeated
verification queries on some older WCH loaders. This is a potentially useful
readback lead, distinct from flashing a memory-dump application. It remains
unverified for Nanoleaf: chip, loader version, reachable entry, accepted ranges,
side effects and protection configuration are unknown. A reported minimum
comparison window and a required known boundary also mean this is not a generic
one-byte read command. No oracle or loader probe was run here.

The thread's [example IAP code](https://www.mikrocontroller.net/attachment/highlight/393344)
was read as text. Its optional TEA decoder uses an externally supplied key; it
contains neither a Nanoleaf key nor a link to the NL82 file format. The TEA
variant is already covered by the finite search. Generic claims about protected
loader ranges do not establish the retail memory layout or recoverability.

## What would change the decision

Safe custom firmware still requires all of the following evidence: exact chip
and board compatibility; loader/startup/protection configuration; an entry path
that survives a broken application without opening this enclosure; preservation
of code, loader and factory settings; and a validated image decoder/encoder and
stock restore procedure. An update file alone satisfies none of the backup or
independent-entry requirements.

The strongest remaining research leads are the unavailable vendor demo/loader
source, manufacturer confirmation of the exact production MCU and closed-case
recovery contract, and deeper decoding with a justified format or known-plaintext
anchor. The WCH verification-oracle report is worth retaining as a conditional
lead, not promoting into instructions for this unit. No flashing, overclocking,
reset, protection changes, loader entry or electrical boot experiments are
justified by the current evidence.
