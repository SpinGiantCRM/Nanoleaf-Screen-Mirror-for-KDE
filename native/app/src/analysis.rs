//! Appearance policies use colours actually present in the zone. The legacy
//! wavelet's range-as-colour and quantized bin-centre colours are not reproduced.
use anyhow::Result;
use nanoleaf_core::sampling::SdrSampler;
pub fn mean(sampler: &SdrSampler, pixels: &[[u8; 3]]) -> Result<[u8; 3]> {
    if pixels.is_empty() {
        return Ok([0; 3]);
    }
    let bytes: Vec<_> = pixels.iter().flatten().copied().collect();
    let view = nanoleaf_core::sampling::SdrRgb8Frame::new(&bytes, pixels.len(), 1, bytes.len())?;
    Ok(sampler
        .sample_zone(
            &view,
            nanoleaf_core::sampling::ZoneRect {
                x: 0,
                y: 0,
                width: pixels.len() as i64,
                height: 1,
            },
        )
        .srgb)
}
pub fn multi_moment(sampler: &SdrSampler, pixels: &[[u8; 3]]) -> Result<[u8; 3]> {
    if pixels.is_empty() {
        return Ok([0; 3]);
    }
    let n = pixels.len() as f64;
    let avg: [f64; 3] =
        std::array::from_fn(|k| pixels.iter().map(|p| f64::from(p[k])).sum::<f64>() / n);
    let variance = pixels
        .iter()
        .map(|p| {
            (0..3)
                .map(|k| (f64::from(p[k]) - avg[k]).powi(2))
                .sum::<f64>()
        })
        .sum::<f64>()
        / (3.0 * n);
    if variance < 1000.0
        || pixels
            .iter()
            .filter(|p| p.iter().max().unwrap().abs_diff(*p.iter().min().unwrap()) >= 5)
            .count()
            * 10
            < pixels.len()
    {
        return mean(sampler, pixels);
    }
    let bin = |p: [u8; 3]| {
        usize::from(p[0] / 32) * 64 + usize::from(p[1] / 32) * 8 + usize::from(p[2] / 32)
    };
    let mut counts = [0_usize; 512];
    for &p in pixels {
        counts[bin(p)] += 1;
    }
    let best = (0..512)
        .max_by_key(|&i| (counts[i], std::cmp::Reverse(i)))
        .unwrap();
    if counts[best] as f64 / n <= 0.15 {
        return mean(sampler, pixels);
    }
    let selected: Vec<_> = pixels.iter().copied().filter(|&p| bin(p) == best).collect();
    mean(sampler, &selected)
}
/// Edge detail biases a linear-light mean, never converts channel ranges into
/// an emitted colour. Uniform, grey and black zones therefore remain exact.
pub fn wavelet(sampler: &SdrSampler, pixels: &[[u8; 3]], width: usize) -> Result<[u8; 3]> {
    if pixels.is_empty() {
        return Ok([0; 3]);
    }
    if pixels.iter().all(|p| *p == pixels[0]) {
        return Ok(pixels[0]);
    }
    let mut weights: Vec<f32> = pixels
        .iter()
        .enumerate()
        .map(|(i, p)| {
            let mut detail = 0_u8;
            for other in [
                i.checked_sub(1)
                    .filter(|j| width > 0 && j / width == i / width),
                i.checked_sub(width).filter(|_| width > 0),
            ]
            .into_iter()
            .flatten()
            {
                detail = detail.max(
                    (0..3)
                        .map(|k| p[k].abs_diff(pixels[other][k]))
                        .max()
                        .unwrap(),
                );
            }
            1.0 + f32::from(detail) / 255.0
        })
        .collect();
    let sum: f32 = weights.iter().sum();
    for w in &mut weights {
        *w /= sum;
    }
    Ok(sampler.weighted_mean(pixels, &weights)?)
}
