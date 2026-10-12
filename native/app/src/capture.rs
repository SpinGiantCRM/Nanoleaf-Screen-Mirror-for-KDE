//! KWin ScreenShot2 capture without Qt, root access or a privileged helper.
use anyhow::{bail, ensure, Context, Result};
use rustix::event::{poll, PollFd, PollFlags, Timespec};
use std::collections::HashMap;
use std::os::fd::OwnedFd;
use std::time::{Duration, Instant};
use zbus::blocking::{Connection, Proxy};
use zbus::zvariant::{Fd, OwnedValue, Value};

pub struct Frame {
    pub width: usize,
    pub height: usize,
    pub pixels: Vec<u8>,
}
pub struct KwinCapture {
    connection: Connection,
    monitor: String,
}
impl KwinCapture {
    pub fn new(monitor: String) -> Result<Self> {
        let connection = zbus::blocking::connection::Builder::session()?
            .method_timeout(Duration::from_secs(2))
            .build()?;
        Ok(Self {
            connection,
            monitor,
        })
    }
    pub fn capture(&self) -> Result<Frame> {
        let proxy = Proxy::new(
            &self.connection,
            "org.kde.KWin.ScreenShot2",
            "/org/kde/KWin/ScreenShot2",
            "org.kde.KWin.ScreenShot2",
        )?;
        let (read, write) = rustix::pipe::pipe()?;
        let fd = Fd::from(&write);
        let options: HashMap<&str, Value<'_>> =
            HashMap::from([("native-resolution", Value::from(true))]);
        let reply: HashMap<String, OwnedValue> = if self.monitor.is_empty() {
            proxy.call("CaptureActiveScreen", &(options, fd))?
        } else {
            proxy.call("CaptureScreen", &(&self.monitor, options, fd))?
        };
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
        let data = read_frame(&read, size, Duration::from_secs(2))?;
        decode(&data, width, height, stride, format)
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
    let mut pixels = Vec::with_capacity(width * height * 3);
    for row in 0..height {
        for pixel in
            data[row * stride..row * stride + width * bytes_per_pixel].chunks_exact(bytes_per_pixel)
        {
            let (rgb, alpha, premultiplied) = match format {
                4..=6 => {
                    let word = u32::from_ne_bytes(pixel.try_into()?);
                    (
                        [(word >> 16) as u8, (word >> 8) as u8, word as u8],
                        (word >> 24) as u8,
                        format == 6,
                    )
                }
                16..=18 => ([pixel[0], pixel[1], pixel[2]], pixel[3], format == 18),
                29 => ([pixel[2], pixel[1], pixel[0]], 255, false),
                _ => ([pixel[0], pixel[1], pixel[2]], 255, false),
            };
            let rgb = if premultiplied {
                rgb.map(|code| {
                    if alpha == 0 {
                        0
                    } else {
                        ((u32::from(code) * 255 + u32::from(alpha) / 2) / u32::from(alpha)).min(255)
                            as u8
                    }
                })
            } else {
                rgb
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
