//! PipeWire's explicit DRM syncobj timeline contract, confined to the capture child.
//! Only the selected Vulkan device's unprivileged render node is opened. No KMS
//! operations, primary node, capabilities, global device waits or image writes.
use anyhow::{ensure, Context, Result};
use ash::vk;
use pipewire::{buffer::Buffer, spa};
use std::{
    fs::{File, OpenOptions},
    os::{
        fd::{AsRawFd, FromRawFd, OwnedFd},
        unix::fs::{FileTypeExt, MetadataExt, OpenOptionsExt},
    },
    time::{Duration, Instant},
};

// Append-only SPA ABI (PipeWire >=1.2). Local definitions retain builds against
// older headers; negotiation is opt-in and unsupported producers fail explicitly.
pub const META_TYPE: u32 = 9;
pub const META_SIZE: usize = 24;
const DATA_SYNCOBJ: u32 = 5;
#[repr(C)]
#[derive(Clone, Copy, Debug, Default)]
struct Meta {
    flags: u32,
    padding: u32,
    acquire: u64,
    release: u64,
}
impl spa::buffer::meta::Metadata for Meta {
    const META_TYPE: u32 = META_TYPE;
}
pub fn present(buffer: &Buffer<'_>) -> bool {
    buffer.find_meta::<Meta>().is_some()
}

// Original Linux syncobj UAPI sizes, supported by both older and newer kernels.
// Newer trailing fields are not needed: flags=0, no deadline or point export.
#[repr(C)]
#[derive(Default)]
struct Handle {
    handle: u32,
    flags: u32,
    fd: i32,
    pad: u32,
}
#[repr(C)]
#[derive(Default)]
struct Destroy {
    handle: u32,
    pad: u32,
}
#[repr(C)]
#[derive(Default)]
struct Wait {
    handles: u64,
    points: u64,
    timeout_ns: i64,
    count: u32,
    flags: u32,
    first: u32,
    pad: u32,
}
#[repr(C)]
#[derive(Default)]
struct Signal {
    handles: u64,
    points: u64,
    count: u32,
    flags: u32,
}
const fn command<T>(number: u32) -> libc::c_ulong {
    ((3_u64 << 30)
        | ((std::mem::size_of::<T>() as u64) << 16)
        | ((b'd' as u64) << 8)
        | number as u64) as libc::c_ulong
}

pub struct Device {
    file: File,
}
impl Device {
    pub fn open(device: &wgpu::Device) -> Result<Self> {
        // SAFETY: Borrowed live HAL; query-only physical device properties.
        let hal = unsafe { device.as_hal::<wgpu::hal::api::Vulkan>() }.context("Not Vulkan")?;
        let instance = hal.shared_instance().raw_instance();
        // SAFETY: Physical device belongs to this guarded Vulkan instance.
        let extensions =
            unsafe { instance.enumerate_device_extension_properties(hal.raw_physical_device()) }?;
        ensure!(
            extensions.iter().any(|e| e
                .extension_name_as_c_str()
                .is_ok_and(|n| n == ash::ext::physical_device_drm::NAME)),
            "Vulkan DRM device identification unavailable"
        );
        let mut drm = vk::PhysicalDeviceDrmPropertiesEXT::default();
        let mut properties = vk::PhysicalDeviceProperties2::default().push_next(&mut drm);
        // SAFETY: Correct output structure chain, live physical device; no mutation.
        unsafe {
            instance.get_physical_device_properties2(hal.raw_physical_device(), &mut properties)
        };
        ensure!(
            drm.has_render != 0 && drm.render_major >= 0 && drm.render_minor >= 128,
            "Vulkan device has no render node"
        );
        let path = std::path::PathBuf::from(format!(
            "/dev/char/{}:{}",
            drm.render_major, drm.render_minor
        ))
        .canonicalize()?;
        ensure!(
            path.parent() == Some(std::path::Path::new("/dev/dri"))
                && path
                    .file_name()
                    .is_some_and(|n| n.to_string_lossy().starts_with("renderD")),
            "Refusing a non-render DRM node"
        );
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
            .open(path)?;
        let meta = file.metadata()?;
        ensure!(
            meta.file_type().is_char_device()
                && libc::major(meta.rdev()) as i64 == drm.render_major
                && libc::minor(meta.rdev()) as i64 == drm.render_minor,
            "DRM render identity changed"
        );
        Ok(Self { file })
    }

    /// Operator diagnostic using only newly created private syncobjs. Does not
    /// import compositor state, capture pixels or access a USB controller.
    pub fn self_test(&self) -> Result<serde_json::Value> {
        #[repr(C)]
        struct Create {
            handle: u32,
            flags: u32,
        }
        struct Owned<'a> {
            device: &'a Device,
            handle: u32,
        }
        impl Drop for Owned<'_> {
            fn drop(&mut self) {
                self.device.destroy(self.handle);
            }
        }
        let mut create = Create {
            handle: 0,
            flags: 0,
        };
        // SAFETY: Initialized writable original drm_syncobj_create ABI; creates
        // a private object in our render-file description, no foreign object.
        let status =
            unsafe { libc::ioctl(self.file.as_raw_fd(), command::<Create>(0xbf), &mut create) };
        ensure!(
            status == 0 && create.handle != 0,
            "Private syncobj create failed: {}",
            std::io::Error::last_os_error()
        );
        let original = Owned {
            device: self,
            handle: create.handle,
        };
        let mut export = Handle {
            handle: original.handle,
            fd: -1,
            ..Default::default()
        };
        // SAFETY: Export only our freshly created private object using exact ABI.
        let status =
            unsafe { libc::ioctl(self.file.as_raw_fd(), command::<Handle>(0xc1), &mut export) };
        ensure!(
            status == 0 && export.fd >= 0,
            "Private syncobj export failed: {}",
            std::io::Error::last_os_error()
        );
        // SAFETY: Successful export returned a fresh exclusively owned FD.
        let fd = unsafe { OwnedFd::from_raw_fd(export.fd) };
        let imported = self.import(fd.as_raw_fd())?;
        let imported_owner = (imported != original.handle).then(|| Owned {
            device: self,
            handle: imported,
        });
        let start = Instant::now();
        let timeout = self
            .wait(imported, 1, Duration::from_millis(10))
            .err()
            .context("Private unsignaled object unexpectedly ready")?;
        ensure!(
            timeout
                .downcast_ref::<std::io::Error>()
                .is_some_and(|e| matches!(
                    e.raw_os_error(),
                    Some(libc::ETIME) | Some(libc::ETIMEDOUT)
                )),
            "Unexpected timeline wait error: {timeout:#}"
        );
        let timeout_ms = start.elapsed().as_secs_f64() * 1000.0;
        for point in 1..=8 {
            self.signal(original.handle, point)?;
            self.wait(imported, point, Duration::from_millis(100))?;
        }
        drop(imported_owner);
        Ok(
            serde_json::json!({"private_timeline_import_signal_wait":true,"points_checked":8,"unsignaled_timeout_ms":timeout_ms,"foreign_objects_accessed":false}),
        )
    }
    fn import(&self, fd: i32) -> Result<u32> {
        ensure!(fd >= 0, "Invalid syncobj FD");
        let mut arg = Handle {
            fd,
            ..Default::default()
        };
        // SAFETY: Kernel validates the borrowed FD; initialized, writable UAPI
        // object has the command's exact size. Neither supplied FD is consumed.
        let result =
            unsafe { libc::ioctl(self.file.as_raw_fd(), command::<Handle>(0xc2), &mut arg) };
        ensure!(
            result == 0 && arg.handle != 0,
            "DRM syncobj import failed: {}",
            std::io::Error::last_os_error()
        );
        Ok(arg.handle)
    }
    fn destroy(&self, handle: u32) {
        let mut arg = Destroy { handle, pad: 0 };
        // SAFETY: This handle was imported into this file description only.
        unsafe { libc::ioctl(self.file.as_raw_fd(), command::<Destroy>(0xc0), &mut arg) };
    }
    fn wait(&self, handle: u32, point: u64, timeout: Duration) -> Result<()> {
        let now = monotonic_ns()?;
        let timeout_ns = now
            .checked_add(timeout.as_nanos().try_into()?)
            .context("Sync timeout overflow")?;
        let mut arg = Wait {
            handles: (&handle as *const u32) as u64,
            points: (&point as *const u64) as u64,
            timeout_ns,
            count: 1,
            flags: 2,
            ..Default::default()
        }; // WAIT_FOR_SUBMIT, not WAIT_AVAILABLE
        loop {
            // SAFETY: Both pointed-to arrays contain one initialized value and
            // remain live for the blocking ioctl. Absolute timeout stays fixed.
            let result =
                unsafe { libc::ioctl(self.file.as_raw_fd(), command::<Wait>(0xca), &mut arg) };
            if result == 0 {
                return Ok(());
            }
            let error = std::io::Error::last_os_error();
            if error.kind() != std::io::ErrorKind::Interrupted {
                return Err(error).context("Explicit producer timeline wait failed");
            }
        }
    }
    fn signal(&self, handle: u32, point: u64) -> Result<()> {
        let mut arg = Signal {
            handles: (&handle as *const u32) as u64,
            points: (&point as *const u64) as u64,
            count: 1,
            flags: 0,
        };
        // SAFETY: One live imported handle/point; no GPU use may remain when
        // called. This affects only the producer-granted release timeline.
        let result =
            unsafe { libc::ioctl(self.file.as_raw_fd(), command::<Signal>(0xcd), &mut arg) };
        ensure!(
            result == 0,
            "Explicit release signal failed: {}",
            std::io::Error::last_os_error()
        );
        Ok(())
    }
}
fn monotonic_ns() -> Result<i64> {
    let mut time = libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    // SAFETY: Valid writable timespec, supported read-only monotonic clock.
    let status = unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut time) };
    ensure!(status == 0, "Monotonic clock unavailable");
    time.tv_sec
        .checked_mul(1_000_000_000)
        .and_then(|t| t.checked_add(time.tv_nsec))
        .context("Clock overflow")
}

pub(crate) struct Lease<'a> {
    device: &'a Device,
    acquire: u32,
    release: u32,
    point: u64,
    pub wait_ms: f64,
    released: bool,
}
impl<'a> Lease<'a> {
    pub fn acquire(buffer: &mut Buffer<'_>, device: &'a Device) -> Result<Self> {
        let meta = *buffer
            .find_meta::<Meta>()
            .context("Explicit sync metadata missing")?;
        validate(meta)?;
        let data = buffer.datas_mut();
        let descriptors: Vec<_> = data.iter().map(|d| (d.type_().as_raw(), d.fd())).collect();
        validate_descriptors(&descriptors)?;
        let acquire = device.import(data[1].fd())?;
        let release = match device.import(data[2].fd()) {
            Ok(handle) => handle,
            Err(error) => {
                device.destroy(acquire);
                return Err(error);
            }
        };
        let mut lease = Self {
            device,
            acquire,
            release,
            point: meta.release,
            wait_ms: 0.0,
            released: true,
        };
        ensure!(
            acquire != release || meta.release > meta.acquire,
            "Release point precedes acquire on shared timeline"
        );
        let started = Instant::now();
        device.wait(acquire, meta.acquire, Duration::from_secs(2))?;
        lease.wait_ms = started.elapsed().as_secs_f64() * 1000.0;
        // From here on, any failure must terminate the capture child before a
        // Buffer drop can return an accessed image without its release fence.
        lease.released = false;
        Ok(lease)
    }
    pub fn release(mut self) -> Result<()> {
        self.device.signal(self.release, self.point)?;
        self.released = true;
        Ok(())
    }
}
impl Drop for Lease<'_> {
    fn drop(&mut self) {
        if !self.released {
            eprintln!("Explicit frame not safely released; terminating isolated capture child");
            std::process::exit(2);
        }
        self.device.destroy(self.acquire);
        if self.release != self.acquire {
            self.device.destroy(self.release);
        }
    }
}
fn validate_descriptors(data: &[(u32, i32)]) -> Result<()> {
    ensure!(
        data.len() == 3
            && data[0].0 == 3
            && data[1].0 == DATA_SYNCOBJ
            && data[2].0 == DATA_SYNCOBJ
            && data.iter().all(|(_, fd)| *fd >= 0),
        "Expected one DMA-BUF image and two valid syncobj FDs"
    );
    Ok(())
}
fn validate(meta: Meta) -> Result<()> {
    ensure!(
        meta.flags == 0 && meta.padding == 0,
        "Unsupported sync timeline flags/layout"
    );
    ensure!(
        meta.acquire > 0 && meta.release > meta.acquire,
        "Unsupported KWin timeline point order"
    );
    Ok(())
}

/// Return unused frames only after their producer has finished. This is required
/// even for latest-frame coalescing, corrupt images, and intentionally skipped work.
pub fn discard(buffer: &mut Buffer<'_>, gpu: &wgpu::Device) -> Result<()> {
    if !present(buffer) {
        return Ok(());
    }
    let meta = *buffer
        .find_meta::<Meta>()
        .context("Missing timeline metadata")?;
    if meta.acquire == 0 && meta.release == 0 && meta.flags == 0 && meta.padding == 0 {
        return Ok(());
    }
    let device = Device::open(gpu)?;
    let lease = Lease::acquire(buffer, &device)?;
    lease.release()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn stable_spa_and_linux_uapi_layouts() {
        assert_eq!(std::mem::size_of::<Meta>(), META_SIZE);
        assert_eq!(std::mem::size_of::<Handle>(), 16);
        assert_eq!(std::mem::size_of::<Wait>(), 40);
        assert_eq!(std::mem::size_of::<Signal>(), 24);
        assert_eq!(command::<Handle>(0xc2), 0xc01064c2);
        assert_eq!(command::<Wait>(0xca), 0xc02864ca);
        assert_eq!(command::<Signal>(0xcd), 0xc01864cd);
    }
    #[test]
    fn image_and_timeline_descriptors_cannot_be_confused() {
        assert!(validate_descriptors(&[(3, 4), (5, 5), (5, 6)]).is_ok());
        assert!(validate_descriptors(&[(3, 4)]).is_err());
        assert!(validate_descriptors(&[(3, 4), (3, 5), (5, 6)]).is_err());
        assert!(validate_descriptors(&[(3, 4), (5, -1), (5, 6)]).is_err());
        assert!(validate_descriptors(&[(2, 4), (5, 5), (5, 6)]).is_err());
    }
    #[test]
    fn unsupported_flags_and_uninitialized_points_are_rejected() {
        assert!(validate(Meta::default()).is_err());
        let valid = Meta {
            acquire: 1,
            release: 2,
            ..Default::default()
        };
        assert!(validate(valid).is_ok());
        assert!(validate(Meta {
            release: 1,
            ..valid
        })
        .is_err());
        assert!(validate(Meta {
            acquire: 3,
            ..valid
        })
        .is_err());
        assert!(validate(Meta { flags: 1, ..valid }).is_err());
        assert!(validate(Meta {
            padding: 1,
            ..valid
        })
        .is_err());
        assert!(validate(Meta {
            release: 0,
            ..valid
        })
        .is_err());
    }
}
