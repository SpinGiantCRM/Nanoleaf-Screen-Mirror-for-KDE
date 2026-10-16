#[path = "../../native/core/src/colour.rs"]
mod colour;
use colour::{apply_profile, LedCalibration, Style};
fn main() {
    for rgb in [
        [255., 0., 0.],
        [0., 255., 0.],
        [0., 0., 255.],
        [120., 90., 75.],
        [128., 128., 128.],
    ] {
        let mut p = LedCalibration::default();
        let a = apply_profile(rgb, Style::Reference, p);
        p.chroma_compression = 0.6;
        let b = apply_profile(rgb, Style::Reference, p);
        println!("{:?}: compression 0 {:?}, compression 0.6 {:?}", rgb, a, b);
    }
    let p = LedCalibration::default();
    println!(
        "gain-clamp {:?} == {:?}",
        apply_profile(
            [100., 80., 60.],
            Style::Reference,
            LedCalibration {
                gains: [0.42; 3],
                ..p
            }
        ),
        apply_profile(
            [100., 80., 60.],
            Style::Reference,
            LedCalibration {
                gains: [0.5; 3],
                ..p
            }
        )
    );
    println!(
        "gamma-clamp {:?} == {:?}",
        apply_profile(
            [100., 80., 60.],
            Style::Reference,
            LedCalibration { gamma: 0.7, ..p }
        ),
        apply_profile(
            [100., 80., 60.],
            Style::Reference,
            LedCalibration { gamma: 1.0, ..p }
        )
    );
}
