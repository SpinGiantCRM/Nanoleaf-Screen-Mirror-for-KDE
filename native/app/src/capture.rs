//! KWin ScreenShot2 capture without Qt, root access or a privileged helper.
use anyhow::{bail, ensure, Context, Result};
use rustix::event::{poll, PollFd, PollFlags, Timespec};
use std::collections::HashMap;
use std::os::fd::OwnedFd;
use std::time::{Duration, Instant};
use zbus::blocking::Proxy;
use zbus::zvariant::{Fd, OwnedValue, Value};

pub struct Frame {
    pub width: usize,
    pub height: usize,
    pub pixels: Vec<u8>,
}
#[derive(Debug, Clone, serde::Serialize)]
pub struct CaptureTimes {
    pub reply_ms: f64,
    pub pipe_ms: f64,
    pub decode_ms: f64,
    pub format: usize,
}
pub struct KwinCapture {
    proxy: Proxy<'static>,
    monitor: String,
}
impl KwinCapture {
    pub fn new(monitor: String) -> Result<Self> {
        let connection = zbus::blocking::connection::Builder::session()?
            .method_timeout(Duration::from_secs(2))
            .build()?;
        let proxy = Proxy::new_owned(
            connection,
            "org.kde.KWin.ScreenShot2",
            "/org/kde/KWin/ScreenShot2",
            "org.kde.KWin.ScreenShot2",
        )?;
        Ok(Self { proxy, monitor })
    }
    pub fn capture(&self) -> Result<Frame> {
        Ok(self.capture_timed()?.0)
    }
    pub fn capture_timed(&self) -> Result<(Frame, CaptureTimes)> {
        let started = Instant::now();
        let (read, write) = rustix::pipe::pipe()?;
        let fd = Fd::from(&write);
        let options: HashMap<&str, Value<'_>> =
            HashMap::from([("native-resolution", Value::from(true))]);
        let reply: HashMap<String, OwnedValue> = if self.monitor.is_empty() {
            self.proxy.call("CaptureActiveScreen", &(options, fd))?
        } else {
            self.proxy
                .call("CaptureScreen", &(&self.monitor, options, fd))?
        };
        let reply_ms = started.elapsed().as_secs_f64() * 1000.0;
        drop(write);
        let kind = <&str>::try_from(reply.get("type").context("Missing capture type")?)?;
        ensure!(kind == "raw", "Unsupported capture payload type");
        let integer = |key: &str| -> Result<usize> {
            let value = reply
                .get(key)
                .with_context(|| format!("Missing capture {key}"))?;
            let n = u32::try_from(value).with_context(|| format!("Invalid capture {key}"))?;
            Ok(n as usize)
        };
        let (width, height, stride, format) = (
            integer("width")?,
            integer("height")?,
            integer("stride")?,
            integer("format")?,
        );
        ensure!(
            width > 0 && height > 0 && width <= 16384 && height <= 16384,
            "Invalid capture dimensions"
        );
        let size = stride
            .checked_mul(height)
            .context("Capture size overflow")?;
        ensure!(size <= 128 * 1024 * 1024, "Capture exceeds 128 MiB");
        let pipe_start = Instant::now();
        let data = read_frame(&read, size, Duration::from_secs(2))?;
        let pipe_ms = pipe_start.elapsed().as_secs_f64() * 1000.0;
        let decode_start = Instant::now();
        let frame = decode(&data, width, height, stride, format)?;
        let decode_ms = decode_start.elapsed().as_secs_f64() * 1000.0;
        Ok((
            frame,
            CaptureTimes {
                reply_ms,
                pipe_ms,
                decode_ms,
                format,
            },
        ))
    }
}

fn read_frame(fd: &OwnedFd, size: usize, timeout: Duration) -> Result<Vec<u8>> {
    let mut data = vec![0; size];
    let mut offset = 0;
    let started = Instant::now();
    while offset < size {
        let remaining = timeout
            .checked_sub(started.elapsed())
            .context("Capture timed out")?;
        let timeout = Timespec {
            tv_sec: remaining.as_secs() as i64,
            tv_nsec: remaining.subsec_nanos() as i64,
        };
        let mut polls = [PollFd::new(fd, PollFlags::IN)];
        ensure!(poll(&mut polls, Some(&timeout))? > 0, "Capture timed out");
        let n = rustix::io::read(fd, &mut data[offset..])?;
        ensure!(n > 0, "Truncated capture pipe");
        offset += n;
    }
    Ok(data)
}

pub fn decode(
    data: &[u8],
    width: usize,
    height: usize,
    stride: usize,
    format: usize,
) -> Result<Frame> {
    let bytes_per_pixel = match format {
        4..=6 | 16..=18 => 4,
        13 | 29 => 3,
        _ => bail!("Unsupported capture colour format {format}; refusing an inaccurate conversion"),
    };
    ensure!(width > 0 && height > 0, "Empty capture");
    ensure!(
        stride >= width.checked_mul(bytes_per_pixel).context("Row overflow")?,
        "Invalid capture stride"
    );
    ensure!(
        data.len() >= stride.checked_mul(height).context("Capture overflow")?,
        "Truncated raw frame"
    );
    let output_size = width
        .checked_mul(height)
        .and_then(|n| n.checked_mul(3))
        .context("RGB size overflow")?;
    // Convert packed capture pixels once. Alpha is checked per small block,
    // retaining exact unpremultiplication without scanning the whole frame first.
    let argb = matches!(format, 4..=6);
    let rgba = matches!(format, 16..=18);
    let premultiplied = matches!(format, 6 | 18);
    if argb || rgba {
        let mut pixels = vec![0; output_size];
        for row in 0..height {
            let source = &data[row * stride..row * stride + width * 4];
            let destination = &mut pixels[row * width * 3..(row + 1) * width * 3];
            if rgba {
                packed_rgb_row::<0, 1, 2, 3>(source, destination, premultiplied);
            } else if cfg!(target_endian = "little") {
                packed_rgb_row::<2, 1, 0, 3>(source, destination, premultiplied);
            } else {
                packed_rgb_row::<1, 2, 3, 0>(source, destination, premultiplied);
            }
        }
        return Ok(Frame {
            width,
            height,
            pixels,
        });
    }
    let mut pixels = Vec::with_capacity(output_size);
    for row in 0..height {
        let source = &data[row * stride..row * stride + width * bytes_per_pixel];
        for pixel in source.chunks_exact(bytes_per_pixel) {
            let rgb = if format == 29 {
                [pixel[2], pixel[1], pixel[0]]
            } else {
                [pixel[0], pixel[1], pixel[2]]
            };
            pixels.extend_from_slice(&rgb);
        }
    }
    Ok(Frame {
        width,
        height,
        pixels,
    })
}

// Four pixels at a time make the opaque path a packed channel shuffle. Every
// non-opaque block and remainder uses the same integer rounding/clamping as the
// scalar QImage reference. No SIMD intrinsics or unchecked accesses are needed.
fn packed_rgb_row<const R: usize, const G: usize, const B: usize, const A: usize>(
    source: &[u8],
    destination: &mut [u8],
    premultiplied: bool,
) {
    let full_source = source.len() / 16 * 16;
    let full_destination = full_source / 4 * 3;
    for (s, d) in source[..full_source]
        .chunks_exact(16)
        .zip(destination[..full_destination].chunks_exact_mut(12))
    {
        if !premultiplied || s[A] & s[A + 4] & s[A + 8] & s[A + 12] == 255 {
            d.copy_from_slice(&[
                s[R],
                s[G],
                s[B],
                s[R + 4],
                s[G + 4],
                s[B + 4],
                s[R + 8],
                s[G + 8],
                s[B + 8],
                s[R + 12],
                s[G + 12],
                s[B + 12],
            ]);
        } else {
            for (s, d) in s.chunks_exact(4).zip(d.chunks_exact_mut(3)) {
                convert_pixel::<R, G, B, A>(s, d, true);
            }
        }
    }
    for (s, d) in source[full_source..]
        .chunks_exact(4)
        .zip(destination[full_destination..].chunks_exact_mut(3))
    {
        convert_pixel::<R, G, B, A>(s, d, premultiplied);
    }
}
fn convert_pixel<const R: usize, const G: usize, const B: usize, const A: usize>(
    source: &[u8],
    destination: &mut [u8],
    premultiplied: bool,
) {
    let mut rgb = [source[R], source[G], source[B]];
    let alpha = source[A];
    if premultiplied && alpha < 255 {
        rgb = rgb.map(|code| {
            if alpha == 0 {
                0
            } else {
                ((u32::from(code) * 255 + u32::from(alpha) / 2) / u32::from(alpha)).min(255) as u8
            }
        });
    }
    destination.copy_from_slice(&rgb);
}

#[cfg(test)]
mod pipe_tests {
    use super::*;
    use std::io::Write;

    fn transfer(data: Vec<u8>, capacity: Option<usize>) -> (Vec<u8>, Duration, usize) {
        let (read, write) = rustix::pipe::pipe().unwrap();
        if let Some(capacity) = capacity {
            // Match the proposed best-effort policy: permission/quota failure
            // keeps the kernel's usable default, never requires privileges.
            let _ = rustix::pipe::fcntl_setpipe_size(&read, capacity);
        }
        let actual_capacity = rustix::pipe::fcntl_getpipe_size(&read).unwrap();
        let size = data.len();
        let writer = std::thread::spawn(move || {
            std::fs::File::from(write).write_all(&data).unwrap();
        });
        let start = Instant::now();
        let received = read_frame(&read, size, Duration::from_secs(2)).unwrap();
        let elapsed = start.elapsed();
        writer.join().unwrap();
        (received, elapsed, actual_capacity)
    }

    #[test]
    fn capture_pipe_preserves_every_byte_across_short_reads_and_capacities() {
        let data: Vec<_> = (0..3 * 1024 * 1024).map(|i| (i * 37) as u8).collect();
        for capacity in [None, Some(1024 * 1024)] {
            let (received, _, _) = transfer(data.clone(), capacity);
            assert_eq!(received, data);
        }
    }

    #[test]
    fn closed_capture_pipe_reports_truncation() {
        let (read, write) = rustix::pipe::pipe().unwrap();
        rustix::io::write(&write, &[1, 2, 3]).unwrap();
        drop(write);
        let error = read_frame(&read, 4, Duration::from_secs(1)).unwrap_err();
        assert!(error.to_string().contains("Truncated"));
    }

    #[test]
    fn open_but_stalled_capture_pipe_remains_bounded() {
        let (read, _write) = rustix::pipe::pipe().unwrap();
        let error = read_frame(&read, 4, Duration::from_millis(20)).unwrap_err();
        assert!(error.to_string().contains("timed out"));
    }

    #[test]
    #[ignore = "operator-run synthetic 4K pipe benchmark, not a CI timing gate"]
    fn paired_4k_pipe_transfer_benchmark() {
        let data: Vec<_> = (0..3840 * 2160 * 4).map(|i| (i * 37) as u8).collect();
        for _ in 0..2 {
            for capacity in [None, Some(1024 * 1024)] {
                assert_eq!(transfer(data.clone(), capacity).0, data);
            }
        }
        let mut trials = Vec::new();
        for pair in 0..12 {
            for enlarged in if pair % 2 == 0 {
                [false, true]
            } else {
                [true, false]
            } {
                let (received, elapsed, capacity) =
                    transfer(data.clone(), enlarged.then_some(1024 * 1024));
                assert_eq!(received, data);
                trials.push(serde_json::json!({"pair":pair,"enlarged":enlarged,
                    "actual_capacity":capacity,"transfer_ms":elapsed.as_secs_f64()*1000.0}));
            }
        }
        println!(
            "{}",
            serde_json::json!({"scope":"Generated 4K raw bytes, paired AB/BA kernel pipe transfers with production reader; no compositor, colour conversion, USB or optical timing. Allocation included in reader timing; exact byte equality in every trial.","trials":trials})
        );
    }
}
