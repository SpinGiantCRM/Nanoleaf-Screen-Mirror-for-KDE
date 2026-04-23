# Physical Calibration Validation Log

Track physical-device calibration validation runs for RC sign-off.

## Entry template

| Date (UTC) | RC version | Device | Environment | Scenario | Result | Evidence | Notes |
|---|---|---|---|---|---|---|---|
| YYYY-MM-DD | vX.Y.Z-rcN | Lightstrip model | Arch Wayland | first-run calibration | pass/fail | link/log path |  |

## Minimum recommendations

- At least one successful first-run calibration on physical hardware.
- At least one restart validation confirming persisted calibration applies.
- Document any user-visible confusion points and workaround guidance.
