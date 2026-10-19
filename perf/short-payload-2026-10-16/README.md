# Short-payload USB measurements — 2026-10-16

See [operator design, observations and limits](../../docs/USB_SHORT_PAYLOAD_RESEARCH.md).

`transactions.json` retains all768 measured transactions as compact metadata,
with full-black preconditioning before every command. Generated neutral8/64,
manual48, full versus valid short prefixes, both pair orders,12 samples/case.
No screen data, saved RGB/calibration coefficients, serial or original controller
preferences are included. `summary.json` excludes the first two samples of each
case uniformly, retaining each order separately and all raw timing samples.
All measured commands succeeded in this run; controller restoration was also
independently verified and all13 config/launcher paths remained byte-identical.

Small prefixes saved about2–4ms transaction time;47-zone versus48-zone command
showed no gain. These are host-observed USB timings, not optical timing or
proof of omitted-zone retention. The announced red-prefix repeat was observed retaining blue in the omitted
remainder. The30-second black-prefix and green-from-black checks confirmed retained red
and retained black in omitted zones. Exact reports and per-run software timings
are tracked separately in observations.json. These findings apply to this tested
NL82K2/firmware0x15/manual48 configuration; no universal firmware claim. Daily acknowledged full-frame output is unchanged.
