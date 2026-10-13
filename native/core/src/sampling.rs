//! Full-pixel SDR sRGB byte sampling. HDR/FP16/PQ are deliberately not accepted.
//! Caller supplies effective rectangles after existing anchoring/privacy logic.

use std::fmt;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Error {
    InvalidDimensions,
    InvalidStride,
    TruncatedFrame,
    GeometryOverflow,
    OutputLength,
    InvalidHistogram,
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for Error {}

#[derive(Debug, Clone, Copy)]
pub struct ZoneRect {
    pub x: i64,
    pub y: i64,
    pub width: i64,
    pub height: i64,
}

/// Borrowed RGB8 pixels, with checked dimensions and explicit byte stride.
pub struct SdrRgb8Frame<'a> {
    pub(crate) data: &'a [u8],
    pub(crate) width: usize,
    pub(crate) height: usize,
    pub(crate) stride: usize,
}

impl<'a> SdrRgb8Frame<'a> {
    pub fn new(data: &'a [u8], width: usize, height: usize, stride: usize) -> Result<Self, Error> {
        if width == 0 || height == 0 {
            return Err(Error::InvalidDimensions);
        }
        i64::try_from(width).map_err(|_| Error::GeometryOverflow)?;
        i64::try_from(height).map_err(|_| Error::GeometryOverflow)?;
        let row_bytes = width.checked_mul(3).ok_or(Error::GeometryOverflow)?;
        if stride < row_bytes {
            return Err(Error::InvalidStride);
        }
        let required = (height - 1)
            .checked_mul(stride)
            .and_then(|offset| offset.checked_add(row_bytes))
            .ok_or(Error::GeometryOverflow)?;
        if data.len() < required {
            return Err(Error::TruncatedFrame);
        }
        Ok(Self {
            data,
            width,
            height,
            stride,
        })
    }
}

#[derive(Debug, Default, Clone, Copy)]
pub struct ZoneSample {
    pub srgb: [u8; 3],
    pub linear_rgb: [f32; 3],
    pub encoded_variance: f64,
    pub pixel_count: u64,
}

pub struct SdrSampler {
    pub(crate) linear_codes: [f32; 256],
}

impl Default for SdrSampler {
    fn default() -> Self {
        let linear_codes = std::array::from_fn(|code| {
            let encoded = code as f64 / 255.0;
            let linear = if encoded <= 0.04045 {
                encoded / 12.92
            } else {
                ((encoded + 0.055) / 1.055).powf(2.4)
            };
            linear as f32
        });
        Self { linear_codes }
    }
}

impl SdrSampler {
    /// Linear-light reduction using caller-supplied, normalized spatial weights.
    /// Preserve float32 weight values with a float64 reduction, as the reference
    /// does. Do not renormalize a calibrated spatial kernel after rounding it.
    pub fn weighted_mean(&self, pixels: &[[u8; 3]], weights: &[f32]) -> Result<[u8; 3], Error> {
        if pixels.len() != weights.len() {
            return Err(Error::OutputLength);
        }
        if weights.iter().any(|w| !w.is_finite() || *w < 0.0) {
            return Err(Error::InvalidDimensions);
        }
        let mut sum = [0.0_f64; 3];
        for (pixel, &weight) in pixels.iter().zip(weights) {
            for c in 0..3 {
                sum[c] += f64::from(self.linear_codes[pixel[c] as usize]) * f64::from(weight);
            }
        }
        Ok(sum.map(|v| encode_srgb(v as f32)))
    }

    pub fn sample_into(
        &self,
        frame: &SdrRgb8Frame<'_>,
        zones: &[ZoneRect],
        output: &mut [ZoneSample],
    ) -> Result<(), Error> {
        if output.len() != zones.len() {
            return Err(Error::OutputLength);
        }
        for (zone, sample) in zones.iter().zip(output.iter_mut()) {
            *sample = self.sample_zone(frame, *zone);
        }
        Ok(())
    }

    pub fn sample_zone(&self, frame: &SdrRgb8Frame<'_>, zone: ZoneRect) -> ZoneSample {
        if zone.width <= 0 || zone.height <= 0 {
            return ZoneSample::default();
        }
        // Match the recovered Python helper's clamp-origin, then clamp-size rule.
        let x = zone.x.clamp(0, frame.width as i64) as usize;
        let y = zone.y.clamp(0, frame.height as i64) as usize;
        let width = (zone.width as u64).min((frame.width - x) as u64) as usize;
        let height = (zone.height as u64).min((frame.height - y) as u64) as usize;
        if width == 0 || height == 0 {
            return ZoneSample::default();
        }
        let mut counts = [[0_u64; 256]; 3];
        for row in y..y + height {
            let offset = row * frame.stride + x * 3;
            for rgb in frame.data[offset..offset + width * 3].chunks_exact(3) {
                counts[0][usize::from(rgb[0])] += 1;
                counts[1][usize::from(rgb[1])] += 1;
                counts[2][usize::from(rgb[2])] += 1;
            }
        }
        // All geometry above is bounded by the validated frame byte length.
        let pixel_count = (width * height) as u64;
        self.reduce_histograms(&counts, pixel_count)
    }

    /// Validate externally produced integer histograms before colour reduction.
    /// A GPU can count pixels exactly and retain this CPU reference's float64
    /// linear-light reduction rather than changing floating summation order.
    pub fn sample_histograms(&self, counts: &[[u64; 256]; 3]) -> Result<ZoneSample, Error> {
        let totals = counts.map(|channel| channel.iter().try_fold(0_u64, |a, &b| a.checked_add(b)));
        let Some(n) = totals[0] else {
            return Err(Error::InvalidHistogram);
        };
        if totals.iter().any(|v| *v != Some(n)) {
            return Err(Error::InvalidHistogram);
        }
        Ok(self.reduce_histograms(counts, n))
    }

    fn reduce_histograms(&self, counts: &[[u64; 256]; 3], pixel_count: u64) -> ZoneSample {
        if pixel_count == 0 {
            return ZoneSample::default();
        }
        let n = pixel_count as f64;
        let mut sample = ZoneSample {
            pixel_count,
            ..ZoneSample::default()
        };
        for (channel, histogram) in counts.iter().enumerate() {
            let mut linear_sum = 0.0;
            let mut encoded_sum = 0.0;
            let mut encoded_square_sum = 0.0;
            for (code, count) in histogram.iter().enumerate() {
                let count = *count as f64;
                let encoded = code as f64;
                linear_sum += count * f64::from(self.linear_codes[code]);
                encoded_sum += count * encoded;
                encoded_square_sum += count * encoded * encoded;
            }
            sample.linear_rgb[channel] = (linear_sum / n) as f32;
            sample.srgb[channel] = encode_srgb(sample.linear_rgb[channel]);
            sample.encoded_variance +=
                (encoded_square_sum / n - (encoded_sum / n).powi(2)).max(0.0) / 3.0;
        }
        sample
    }
}

fn encode_srgb(linear: f32) -> u8 {
    let linear = f64::from(linear).clamp(0.0, 1.0);
    let encoded = if linear <= 0.0031308 {
        12.92 * linear
    } else {
        1.055 * linear.powf(1.0 / 2.4) - 0.055
    };
    (encoded * 255.0).round_ties_even().clamp(0.0, 255.0) as u8
}
