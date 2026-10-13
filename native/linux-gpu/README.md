# Linux GPU interop boundary

Experimental private implementation for the isolated capture probe, using ash,
wgpu HAL and PipeWire. The app and colour core retain their unsafe-code ban.
Unsafe blocks here document Vulkan/FD ownership and lifetime assumptions.

`DmaSampler` exposes only zone statistics and optional diagnostic bytes. Imported
textures remain private, so callers cannot retain a texture after returning its
PipeWire buffer. Four imported images are cached by DMA-BUF inode/device and
format/layout. Vulkan submissions go through wgpu queue synchronization. Producer
fence wait and foreign queue ownership transfers bracket every frame.

Only checked, single-plane BGRA/RGBA modifiers are negotiated. Extra planes,
explicit SyncTimeline and premultiplied formats are not supported by this pilot.
It is not a generic renderer or privileged DRM capture helper. GPU completion
failure exits the isolated probe; do not link this failure policy into the tray
process before adding the capture subprocess/recovery integration.

See [measurements and adoption gates](../../docs/RUST_STREAM_VULKAN.md).
