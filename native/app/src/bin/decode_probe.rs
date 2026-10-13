//! Synthetic raw capture conversion attribution. No D-Bus, USB or user config.
use anyhow::Result;
use nanoleaf_native::capture::decode;
use std::{hint::black_box, time::Instant};
// Frozen pre-specialization format-6 loop. Benchmark-only reference, not a
// selectable production backend. Keep alpha handling identical in both paths.
#[inline(never)]
fn reference(data: &[u8], width: usize, height: usize) -> Vec<u8> {
    let mut pixels = Vec::with_capacity(width * height * 3);
    for pixel in data.chunks_exact(4) {
        let word = u32::from_ne_bytes(pixel.try_into().unwrap());
        let alpha = (word >> 24) as u8;
        let rgb = [(word >> 16) as u8, (word >> 8) as u8, word as u8];
        let rgb = if alpha < 255 {
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
    pixels
}
fn main() -> Result<()> {
    let mut cases = Vec::new();
    for (width, height) in [(2560, 1440), (3840, 2160)] {
        for alpha in [255_u8, 128] {
            let mut data = Vec::with_capacity(width * height * 4);
            for i in 0..width * height {
                let c = ((i * 37) % (alpha as usize + 1)) as u32;
                let green = ((i * 19) % (alpha as usize + 1)) as u32;
                let blue = ((i * 11) % (alpha as usize + 1)) as u32;
                data.extend_from_slice(
                    &((alpha as u32) << 24 | c << 16 | green << 8 | blue).to_ne_bytes(),
                );
            }
            for _ in 0..3 {
                black_box(decode(black_box(&data), width, height, width * 4, 6)?);
                black_box(reference(black_box(&data), width, height));
            }
            assert_eq!(
                decode(&data, width, height, width * 4, 6)?.pixels,
                reference(&data, width, height)
            );
            let mut times = Vec::new();
            let mut baseline = Vec::new();
            for iteration in 0..20 {
                for native in if iteration % 2 == 0 {
                    [true, false]
                } else {
                    [false, true]
                } {
                    let start = Instant::now();
                    if native {
                        black_box(decode(black_box(&data), width, height, width * 4, 6)?);
                    } else {
                        black_box(reference(black_box(&data), width, height));
                    }
                    let time = start.elapsed().as_secs_f64() * 1000.0;
                    if native {
                        times.push(time);
                    } else {
                        baseline.push(time);
                    }
                }
            }
            cases.push(
                serde_json::json!({"width":width,"height":height,"alpha":alpha,"decode_ms":times,"reference_ms":baseline,"pixel_parity":true}),
            );
        }
    }
    println!(
        "{}",
        serde_json::json!({"scope":"Synthetic Qt ARGB32 premultiplied to RGB8, allocation included, no capture/USB/GUI","cases":cases})
    );
    Ok(())
}
