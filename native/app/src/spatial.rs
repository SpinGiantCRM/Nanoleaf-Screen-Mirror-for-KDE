//! Spatial edge kernels for the existing non-box sampling policy.
pub fn weights(
    rect: [usize; 4],
    frame: [usize; 2],
    mode: &str,
    locality: &str,
) -> Option<Vec<f32>> {
    let [x, y, width, height] = rect;
    let [frame_width, frame_height] = frame;
    if width == 0 || height == 0 {
        return None;
    }
    let orientation = if y == 0 && height as f64 <= (frame_height as f64 * 0.22).max(2.0) {
        0
    } else if y + height >= frame_height && height as f64 <= (frame_height as f64 * 0.22).max(2.0) {
        1
    } else if x == 0 && width as f64 <= (frame_width as f64 * 0.22).max(2.0) {
        2
    } else if x + width >= frame_width && width as f64 <= (frame_width as f64 * 0.22).max(2.0) {
        3
    } else {
        return None;
    };
    let (bias, sigma) = match locality {
        "tight" => (8.0_f32, 0.18_f32),
        "wide" => (4.2, 0.34),
        _ => (5.8, 0.25),
    };
    let extent = if orientation < 2 { height } else { width };
    let depth = ((extent as f64 * 0.35).ceil() as usize)
        .clamp(2, 8)
        .min(extent)
        .max(1);
    let mut out = Vec::with_capacity(width * height);
    for row in 0..height {
        for col in 0..width {
            let distance = match orientation {
                0 => row,
                1 => height - row - 1,
                2 => col,
                _ => width - col - 1,
            };
            let weight = if mode == "edge_direct" {
                if distance < depth {
                    1.0
                } else {
                    0.0
                }
            } else {
                let u = if orientation < 2 {
                    (col as f32 + 0.5) / width as f32
                } else {
                    (row as f32 + 0.5) / height as f32
                };
                let center = (-0.5 * ((u - 0.5) / sigma).powi(2)).exp();
                center * (-bias * ((distance as f32 + 0.5) / extent as f32)).exp()
            };
            out.push(weight);
        }
    }
    // A double precision sum only affects float32 kernel normalization at its
    // rounding boundary. The oracle gates the resulting 8-bit colour to 1 code.
    let sum = out.iter().map(|&v| f64::from(v)).sum::<f64>() as f32;
    for value in &mut out {
        *value /= sum;
    }
    Some(out)
}
