//! Operator-only damage census. Never authorizes colour/sample reuse.
use nanoleaf_core::sampling::ZoneRect;

pub struct Audit {
    buffers: u64,
    missing: u64,
    invalid: u64,
    empty: u64,
    full: u64,
    local: u64,
    sequence_breaks: u64,
    previous: Option<u64>,
    affected: [u64; 49],
}

impl Default for Audit {
    fn default() -> Self {
        Self {
            buffers: 0,
            missing: 0,
            invalid: 0,
            empty: 0,
            full: 0,
            local: 0,
            sequence_breaks: 0,
            previous: None,
            affected: [0; 49],
        }
    }
}

impl Audit {
    pub fn record(
        &mut self,
        dimensions: Option<(u32, u32)>,
        regions: Option<&[ZoneRect]>,
        valid: bool,
        sequence: Option<u64>,
    ) {
        self.buffers += 1;
        if sequence.is_none()
            || self
                .previous
                .is_some_and(|last| sequence != last.checked_add(1))
        {
            self.sequence_breaks += 1;
        }
        self.previous = sequence;
        let Some(regions) = regions else {
            self.missing += 1;
            return;
        };
        let Some((width, height)) = dimensions.filter(|(w, h)| *w > 0 && *h > 0) else {
            self.invalid += 1;
            return;
        };
        if !valid
            || regions.iter().any(|r| {
                r.x < 0
                    || r.y < 0
                    || r.width <= 0
                    || r.height <= 0
                    || r.x.checked_add(r.width).is_none_or(|x| x > width as i64)
                    || r.y.checked_add(r.height).is_none_or(|y| y > height as i64)
            })
        {
            self.invalid += 1;
            return;
        }
        if regions.is_empty() {
            self.empty += 1;
        } else if regions
            .iter()
            .any(|r| r.x == 0 && r.y == 0 && r.width == width as i64 && r.height == height as i64)
        {
            self.full += 1;
        } else {
            self.local += 1;
        }
        // Fixed diagnostic perimeter only, never the user's calibration/mapping.
        let affected = super::zones(width as usize, height as usize)
            .iter()
            .filter(|z| {
                regions.iter().any(|r| {
                    r.x < z.x + z.width
                        && r.x + r.width > z.x
                        && r.y < z.y + z.height
                        && r.y + r.height > z.y
                })
            })
            .count();
        self.affected[affected] += 1;
    }

    pub fn report(&self) -> serde_json::Value {
        serde_json::json!({
            "scope": "Metadata census of every dequeued buffer, including discarded buffers; no pixel reads, GPU sampling or colour reuse. Fixed 48-zone diagnostic perimeter, not user mapping. Empty damage does not establish pixel equality.",
            "buffers": self.buffers,
            "missing_metadata": self.missing,
            "invalid_metadata_or_header": self.invalid,
            "empty_damage": self.empty,
            "full_frame_rectangle": self.full,
            "local_rectangles": self.local,
            "missing_or_nonconsecutive_sequence": self.sequence_breaks,
            "affected_diagnostic_zones_histogram": self.affected.as_slice(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn missing_invalid_empty_and_full_are_distinct() {
        let mut audit = Audit::default();
        audit.record(Some((1200, 700)), None, true, Some(0));
        audit.record(Some((1200, 700)), Some(&[]), false, Some(1));
        audit.record(Some((1200, 700)), Some(&[]), true, Some(2));
        audit.record(
            Some((1200, 700)),
            Some(&[ZoneRect {
                x: 0,
                y: 0,
                width: 1200,
                height: 700,
            }]),
            true,
            Some(3),
        );
        assert_eq!(
            (audit.missing, audit.invalid, audit.empty, audit.full),
            (1, 1, 1, 1)
        );
        assert_eq!(audit.affected[0], 1);
        assert_eq!(audit.affected[48], 1);
        assert_eq!(audit.sequence_breaks, 0);
    }
    #[test]
    fn local_damage_and_bad_coordinates_do_not_authorize_reuse() {
        let mut audit = Audit::default();
        let mut rect = ZoneRect {
            x: 550,
            y: 300,
            width: 10,
            height: 10,
        };
        audit.record(Some((1200, 700)), Some(&[rect]), true, Some(1));
        rect.x = -1;
        audit.record(Some((1200, 700)), Some(&[rect]), true, Some(3));
        rect.x = i64::MAX;
        audit.record(Some((1200, 700)), Some(&[rect]), true, None);
        assert_eq!((audit.local, audit.invalid, audit.affected[0]), (1, 2, 1));
        assert_eq!(audit.sequence_breaks, 2);
    }

    #[test]
    fn touching_zone_boundary_is_not_an_intersection() {
        let mut audit = Audit::default();
        // The left perimeter is [0, 85) at this resolution. These positions
        // are below the top perimeter and away from the other three edges.
        for x in [85, 84] {
            audit.record(
                Some((1200, 700)),
                Some(&[ZoneRect {
                    x,
                    y: 100,
                    width: 1,
                    height: 1,
                }]),
                true,
                Some(x as u64),
            );
        }
        assert_eq!(audit.affected[0], 1);
        assert_eq!(audit.affected[1], 1);
    }
}
