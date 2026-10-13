//! Checked packed SDR extraction; no HDR assumptions or DMA-BUF mmap.
use anyhow::{ensure, Context, Result};
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Packing {
    Bgra,
    Bgrx,
    Rgba,
    Rgbx,
}
#[derive(Clone, Copy)]
pub struct Layout {
    pub width: usize,
    pub height: usize,
    pub stride: i32,
    pub offset: usize,
    pub size: usize,
    pub packing: Packing,
    pub premultiplied: bool,
}
pub fn rgb(data: &[u8], layout: Layout, result: &mut Vec<u8>) -> Result<()> {
    let Layout {
        width,
        height,
        stride,
        offset,
        size,
        packing,
        premultiplied,
    } = layout;
    ensure!(
        width > 0 && height > 0 && width <= 16384 && height <= 16384 && stride > 0,
        "Invalid frame geometry/stride"
    );
    let row = width.checked_mul(4).context("Row overflow")?;
    let stride = usize::try_from(stride)?;
    ensure!(stride >= row, "Short frame stride");
    let end = offset.checked_add(size).context("Chunk overflow")?;
    ensure!(
        end <= data.len() && size <= 128 * 1024 * 1024,
        "Chunk exceeds mapped storage"
    );
    let used = stride
        .checked_mul(height - 1)
        .and_then(|n| n.checked_add(row))
        .context("Frame overflow")?;
    ensure!(used <= size, "Incomplete frame rows");
    let bytes = width
        .checked_mul(height)
        .and_then(|n| n.checked_mul(3))
        .context("RGB overflow")?;
    ensure!(bytes <= 128 * 1024 * 1024, "RGB frame limit");
    result.resize(bytes, 0);
    for y in 0..height {
        let source = &data[offset + y * stride..offset + y * stride + row];
        let target = &mut result[y * width * 3..(y + 1) * width * 3];
        for (pixel, output) in source.chunks_exact(4).zip(target.chunks_exact_mut(3)) {
            let channels = match packing {
                Packing::Bgra | Packing::Bgrx => [pixel[2], pixel[1], pixel[0]],
                _ => [pixel[0], pixel[1], pixel[2]],
            };
            let alpha = match packing {
                Packing::Bgra | Packing::Rgba => pixel[3],
                _ => 255,
            };
            for c in 0..3 {
                output[c] = if alpha == 0 {
                    0
                } else if premultiplied && alpha < 255 {
                    ((u32::from(channels[c]) * 255 + u32::from(alpha) / 2) / u32::from(alpha))
                        .min(255) as u8
                } else {
                    channels[c]
                };
            }
        }
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn padding_offsets_alpha_and_bounds() {
        let data = [99, 99, 10, 20, 30, 255, 90, 90, 0, 64, 128, 128];
        let mut out = Vec::new();
        let mut l = Layout {
            width: 1,
            height: 2,
            stride: 6,
            offset: 2,
            size: 10,
            packing: Packing::Bgra,
            premultiplied: true,
        };
        rgb(&data, l, &mut out).unwrap();
        assert_eq!(out, [30, 20, 10, 255, 128, 0]);
        l.size = 9;
        assert!(rgb(&data, l, &mut out).is_err());
        l.size = 10;
        l.stride = -6;
        assert!(rgb(&data, l, &mut out).is_err());
        l.stride = 6;
        l.offset = usize::MAX;
        assert!(rgb(&data, l, &mut out).is_err());
    }
    #[test]
    fn neutral_black_and_opaque_packings() {
        for packing in [Packing::Bgra, Packing::Bgrx, Packing::Rgba, Packing::Rgbx] {
            let mut out = Vec::new();
            rgb(
                &[128, 128, 128, 255, 0, 0, 0, 255],
                Layout {
                    width: 2,
                    height: 1,
                    stride: 8,
                    offset: 0,
                    size: 8,
                    packing,
                    premultiplied: false,
                },
                &mut out,
            )
            .unwrap();
            assert_eq!(out, [128, 128, 128, 0, 0, 0]);
        }
    }
}
