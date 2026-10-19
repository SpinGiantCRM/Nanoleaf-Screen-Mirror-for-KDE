# Native feature and evidence map

| Area | Active implementation | Regression/evidence |
| --- | --- | --- |
| Single-strip/manual mapping | `native/app/src/geometry.rs` | Native geometry/config fixtures and tests |
| Calibration preservation | `native/app/src/config.rs` | Migration, unknown-field, exact-backup and stale-save tests |
| Colour/black/dithering | `native/app/src/pipeline.rs` | Independent core/app colour and temporal accuracy tests |
| Capture | KWin automatic; explicit portal/Vulkan | Capture contract tests; live parity is separate |
| USB | Serial ACK; qualified exact shorter prefixes | Protocol/transport tests and physical reconnect evidence |
| Settings/tray | Rust egui/ksni, on-demand Settings | UI/config contracts; live desktop checks separate |
| Prediction | Conservative opt-in; disabled in reference/dither modes | Native prediction tests; no guaranteed optical FPS |
| Packaging | Paired immutable native bundle | Isolated install/upgrade/rollback/uninstall contracts |
| Gameplay profiling | Metadata-only observation tool | Real-workload stage/resource measurements; no optical claim |

Python/PyQt, the Python bridge, C DRM helper, Python benchmark CLI, PyPI/AUR
packaging and old auto-probe are retired. Raw HDR formats, native privileged DRM,
multi-device support and automatic count promotion are not supported. Historical
research remains evidence of its original implementation, not a promise of
current UI controls. See [native install](NATIVE_INSTALL.md) for supported use.
