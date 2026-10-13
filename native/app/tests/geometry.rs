use nanoleaf_native::{config::Config, geometry};
use serde::Deserialize;
#[derive(Deserialize)]
struct Case {
    count: usize,
    width: usize,
    height: usize,
    locality: String,
    inset: f64,
    scale: f64,
    anchors: [i64; 4],
    zones: Vec<[i64; 4]>,
    counts: [usize; 4],
    mapping: Vec<usize>,
}
#[test]
fn layouts_and_physical_anchors_preserve_84_reference_cases() {
    let cases: Vec<Case> =
        serde_json::from_str(include_str!("../../fixtures/geometry.json")).unwrap();
    for (index, case) in cases.into_iter().enumerate() {
        let mut c = Config {
            device_zone_count: case.count,
            edge_locality: case.locality,
            layout_inset: case.inset,
            layout_scale: case.scale,
            ..Default::default()
        };
        let [a, b, d, e] = case.anchors;
        c.calibration.corner_anchor_top_left = a;
        c.calibration.corner_anchor_top_right = b;
        c.calibration.corner_anchor_bottom_right = d;
        c.calibration.corner_anchor_bottom_left = e;
        let (zones, counts) = geometry::pixel_zones(&c, case.width, case.height).unwrap();
        assert_eq!(counts, case.counts, "case {index}");
        assert_eq!(
            zones
                .iter()
                .map(|z| [z.x, z.y, z.width, z.height])
                .collect::<Vec<_>>(),
            case.zones,
            "case {index}"
        );
        assert_eq!(
            geometry::calibrated_mapping(&c, zones.len(), counts).unwrap(),
            case.mapping,
            "case {index}"
        );
        c.calibration.reverse_zones = true;
        let mut reverse = case.mapping;
        reverse.reverse();
        assert_eq!(
            geometry::calibrated_mapping(&c, zones.len(), counts).unwrap(),
            reverse
        );
    }
}
