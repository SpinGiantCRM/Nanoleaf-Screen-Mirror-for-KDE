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
proof of omitted-zone retention. The first physical red-prefix run is awaiting
its operator observation. Daily acknowledged full-frame output is unchanged.
