# Native prediction

4D prediction is opt-in. The native predictor is conservative: it bounds inferred
colour steps and extra output, resets on source discontinuity/recovery and counts
predicted packets separately from captured frames. It never increases the true
capture rate or proves a particular optical FPS.

Reference/accuracy mode bypasses prediction. Temporal dithering also disables it;
prediction must not change the acknowledged dither phase or calibrated output.
Predicted packets use full output frames rather than retained trailing-zone
updates. The existing Target capture/output FPS control remains the only FPS
control. No 120 FPS guarantee is made.

See `native/app/src/prediction.rs`, `native/app/tests/prediction.rs` and
[Rust completion evidence](RUST_NATIVE_COMPLETION.md). The retired Python 4D
preset and DRM-zone-patch side effects do not describe the native application.
