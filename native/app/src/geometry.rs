use crate::config::{Config, Rect};
use anyhow::{ensure, Result};
use nanoleaf_core::sampling::ZoneRect;

pub fn edge_zones(
    count: usize,
    width: usize,
    height: usize,
    locality: &str,
) -> (Vec<Rect>, [usize; 4]) {
    let lengths = [width as f64, height as f64, width as f64, height as f64];
    let perimeter = lengths.iter().sum::<f64>();
    let raw = lengths.map(|v| count as f64 * v / perimeter);
    let mut counts = raw.map(|v| (v as usize).max(1));
    if count < 4 {
        counts = [0; 4];
        counts.iter_mut().take(count).for_each(|n| *n = 1);
    } else {
        let mut order = [0, 1, 2, 3];
        order.sort_by(|&a, &b| {
            (raw[b] - counts[b] as f64)
                .total_cmp(&(raw[a] - counts[a] as f64))
                .then(lengths[b].total_cmp(&lengths[a]))
        });
        for i in 0..count.saturating_sub(counts.iter().sum()) {
            counts[order[i % 4]] += 1;
        }
        if counts.iter().sum::<usize>() > count {
            order.sort_by(|&a, &b| {
                (counts[b] as f64 - raw[b])
                    .total_cmp(&(counts[a] as f64 - raw[a]))
                    .then(lengths[b].total_cmp(&lengths[a]))
            });
            let mut excess = counts.iter().sum::<usize>() - count;
            for index in order {
                while excess > 0 && counts[index] > 1 {
                    counts[index] -= 1;
                    excess -= 1;
                }
            }
        }
    }
    let target = match locality {
        "tight" => 0.055,
        "wide" => 0.090,
        _ => 0.070,
    };
    let thickness = 0.05 + (target - 0.05) * ((count as f64 - 8.0) / 40.0).clamp(0.0, 1.0);
    let mut zones = Vec::with_capacity(count);
    for (side, &n) in counts.iter().enumerate() {
        for i in 0..n {
            let t = i as f64 / n as f64;
            let size = 1.0 / n as f64;
            zones.push(match side {
                0 => Rect {
                    x: t,
                    y: 0.0,
                    w: size,
                    h: thickness,
                },
                1 => Rect {
                    x: 1.0 - thickness,
                    y: t,
                    w: thickness,
                    h: size,
                },
                2 => Rect {
                    x: (n - 1 - i) as f64 / n as f64,
                    y: 1.0 - thickness,
                    w: size,
                    h: thickness,
                },
                _ => Rect {
                    x: 0.0,
                    y: (n - 1 - i) as f64 / n as f64,
                    w: thickness,
                    h: size,
                },
            });
        }
    }
    (zones, counts)
}

pub fn pixel_zones(
    config: &Config,
    width: usize,
    height: usize,
) -> Result<(Vec<ZoneRect>, [usize; 4])> {
    ensure!(
        config.device_zone_count > 0,
        "Set the manual strip zone count before starting"
    );
    ensure!(width > 0 && height > 0, "Empty frame geometry");
    let (mut zones, counts) = if config.zones.is_empty() {
        if matches!(
            config.layout_preset.as_str(),
            "horizontal_debug" | "horizontal"
        ) {
            (
                (0..config.device_zone_count)
                    .map(|i| Rect {
                        x: i as f64 / config.device_zone_count as f64,
                        y: 0.0,
                        w: 1.0 / config.device_zone_count as f64,
                        h: 1.0,
                    })
                    .collect(),
                [0; 4],
            )
        } else {
            edge_zones(
                config.device_zone_count,
                width,
                height,
                &config.edge_locality,
            )
        }
    } else {
        let counts = if config.source_side_counts.len() == 4 {
            std::array::from_fn(|i| config.source_side_counts[i])
        } else {
            edge_zones(config.zones.len(), width, height, &config.edge_locality).1
        };
        (config.zones.clone(), counts)
    };
    if config.zones.is_empty()
        && !matches!(
            config.layout_preset.as_str(),
            "horizontal_debug" | "horizontal"
        )
    {
        let inset = config.layout_inset.clamp(0.0, 0.4);
        let scale = config.layout_scale.clamp(0.5, 1.0);
        if inset > 1e-6 || (scale - 1.0).abs() > 1e-6 {
            for z in &mut zones {
                let cx = 0.5 + (z.x + z.w * 0.5 - 0.5) * scale;
                let cy = 0.5 + (z.y + z.h * 0.5 - 0.5) * scale;
                z.w *= scale;
                z.h *= scale;
                z.x = (cx - z.w * 0.5).min(1.0 - inset - z.w).max(inset);
                z.y = (cy - z.h * 0.5).min(1.0 - inset - z.h).max(inset);
                z.w = z.w.min(1.0 - z.x).max(1e-6);
                z.h = z.h.min(1.0 - z.y).max(1e-6);
            }
        }
    }
    Ok((
        zones
            .into_iter()
            .map(|z| ZoneRect {
                x: (z.x * width as f64) as i64,
                y: (z.y * height as f64) as i64,
                width: (z.w * width as f64) as i64,
                height: (z.h * height as f64) as i64,
            })
            .collect(),
        counts,
    ))
}

pub fn calibrated_mapping(
    config: &Config,
    source_count: usize,
    side_counts: [usize; 4],
) -> Result<Vec<usize>> {
    let total = config.device_zone_count;
    ensure!(
        total >= 4 && source_count > 0,
        "Four-corner calibration requires at least 4 strip zones"
    );
    let anchors = config.anchors();
    ensure!(
        anchors.iter().all(|&n| n >= 0 && n < total as i64),
        "Calibration is incomplete; set all four corner anchors"
    );
    for i in 0..4 {
        for j in i + 1..4 {
            ensure!(anchors[i] != anchors[j], "Corner anchors must be unique");
        }
    }
    let cw = anchors.map(|n| n as usize);
    let ccw = [cw[0], cw[3], cw[2], cw[1]];
    let lengths =
        |a: [usize; 4]| std::array::from_fn::<_, 4, _>(|i| (a[(i + 1) % 4] + total - a[i]) % total);
    let score = |a: [usize; 4]| {
        lengths(a)
            .map(|n| (n as f64 - total as f64 / 4.0).powi(2))
            .iter()
            .sum::<f64>()
    };
    let reverse = score(ccw) < score(cw);
    let ordered = if reverse { ccw } else { cw };
    let bounds = if side_counts.iter().sum::<usize>() == source_count {
        let [top, right, bottom, _] = side_counts;
        if reverse {
            [0, top + right + bottom, top + right, top, source_count]
        } else {
            [0, top, top + right, top + right + bottom, source_count]
        }
    } else if reverse {
        [
            0,
            3 * source_count / 4,
            source_count / 2,
            source_count / 4,
            source_count,
        ]
    } else {
        [
            0,
            source_count / 4,
            source_count / 2,
            3 * source_count / 4,
            source_count,
        ]
    };
    let mut mapping = vec![0; total];
    for (edge, steps) in lengths(ordered).into_iter().enumerate() {
        for step in 0..steps {
            let index = (ordered[edge] + step) % total;
            let source = bounds[edge] as f64
                + (bounds[edge + 1] as f64 - bounds[edge] as f64) * step as f64 / steps as f64;
            mapping[index] = source.round_ties_even() as usize % source_count;
        }
    }
    if config.calibration.reverse_zones {
        mapping.reverse();
    }
    Ok(mapping)
}
