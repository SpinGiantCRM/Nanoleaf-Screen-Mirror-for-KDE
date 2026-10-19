//! Conservative classification of the existing ordered float32 luma mean.
//! Ambiguous values require original pixels and the original CPU calculation.

/// Bounds the CPU expression `(0.2126*r + 0.7152*g + 0.0722*b).sum()/n`.
/// Nonnegative terms permit a relative gamma bound. Use EPSILON (twice unit
/// roundoff), n+8 operations and an extra absolute f64 margin. Coefficients are
/// converted FROM f32 so their representation matches the reference exactly.
/// No subnormal/overflow is possible for RGB8 and n<=16384. See Higham (1993),
/// The Accuracy of Floating Point Summation, for the gamma_n summation bound.
pub fn certify_luma_above(totals: [u32; 4], threshold: f32) -> Option<bool> {
    let [r, g, b, n] = totals;
    if n == 0
        || n > 16384
        || !threshold.is_finite()
        || !(0.0..=255.0).contains(&threshold)
        || [r, g, b].iter().any(|&s| s > n * 255)
    {
        return None;
    }
    let mean = (f64::from(r) * f64::from(0.2126_f32)
        + f64::from(g) * f64::from(0.7152_f32)
        + f64::from(b) * f64::from(0.0722_f32))
        / f64::from(n);
    let nu = (f64::from(n) + 8.0) * f64::from(f32::EPSILON);
    let error = mean * nu / (1.0 - nu) + 1e-9;
    if mean - error > f64::from(threshold) {
        Some(true)
    } else if mean + error <= f64::from(threshold) {
        Some(false)
    } else {
        None
    }
}

pub(crate) fn line_index(position: u32, limit: u32) -> Option<usize> {
    if position >= limit {
        return None;
    }
    if position.is_multiple_of(8) {
        Some((position / 8) as usize)
    } else if (limit - 1 - position).is_multiple_of(8) {
        Some((limit.div_ceil(8) + (limit - 1 - position) / 8) as usize)
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn certificates_match_independent_ordered_pixel_reference_or_require_fallback() {
        let mut accepted = 0;
        let mut uncertain = 0;
        for n in [1, 7, 8, 31, 32, 359, 641, 2160, 3840, 16384] {
            for seed in 0..160_u32 {
                let mut totals = [0, 0, 0, n];
                let mut sum = 0.0_f32;
                let mut state = seed + 1;
                for _ in 0..n {
                    let rgb: [u32; 3] = std::array::from_fn(|_| {
                        state = state.wrapping_mul(1664525).wrapping_add(1013904223);
                        match seed % 5 {
                            0 => 4,
                            1 => (state >> 16) % 9,
                            2 => (state >> 16) % 4,
                            3 => (state >> 16) % 256,
                            _ => {
                                if state.is_multiple_of(53) {
                                    200
                                } else {
                                    0
                                }
                            }
                        }
                    });
                    for k in 0..3 {
                        totals[k] += rgb[k];
                    }
                    sum += 0.2126 * rgb[0] as f32 + 0.7152 * rgb[1] as f32 + 0.0722 * rgb[2] as f32;
                }
                match certify_luma_above(totals, 4.0) {
                    Some(value) => {
                        assert_eq!(value, sum / n as f32 > 4.0, "n={n}, seed={seed}");
                        accepted += 1;
                    }
                    None => uncertain += 1,
                }
            }
        }
        assert!(accepted > 1000 && uncertain >= 300);
        assert_eq!(
            certify_luma_above([4 * 3840, 4 * 3840, 4 * 3840, 3840], 4.0),
            None
        );
        for bad in [[0, 0, 0, 0], [0, 0, 0, 16385], [256, 0, 0, 1]] {
            assert_eq!(certify_luma_above(bad, 4.0), None);
        }
        assert_eq!(certify_luma_above([0, 0, 0, 1], f32::NAN), None);
    }
    #[test]
    fn scan_grid_indexes_forward_reverse_duplicates_and_outside_positions() {
        for limit in [1_u32, 7, 8, 9, 359, 2160, 16384] {
            let grid: Vec<_> = (0..limit)
                .step_by(8)
                .chain((0..limit).rev().step_by(8))
                .collect();
            for position in 0..=limit {
                assert_eq!(
                    line_index(position, limit).map(|i| grid[i]),
                    grid.iter().find(|&&p| p == position).copied()
                );
            }
        }
    }
}
