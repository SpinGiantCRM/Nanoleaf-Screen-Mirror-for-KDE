//! Development-only SDR bridge. Immutable Python bytes avoid buffer lifetime,
//! concurrent mutation and arbitrary-stride pointer hazards. No raw-pointer FFI.

use nanoleaf_core::sampling::{SdrRgb8Frame, SdrSampler, ZoneRect, ZoneSample};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

#[pyclass]
struct BoxSampler {
    sampler: SdrSampler,
}

#[pymethods]
impl BoxSampler {
    #[new]
    fn new() -> Self {
        Self {
            sampler: SdrSampler::default(),
        }
    }

    fn sample<'py>(
        &self,
        py: Python<'py>,
        pixels: &Bound<'py, PyBytes>,
        width: usize,
        height: usize,
        zones: Vec<(i64, i64, i64, i64)>,
        transfer: &str,
    ) -> PyResult<(Bound<'py, PyBytes>, Bound<'py, PyBytes>)> {
        if transfer != "srgb" {
            return Err(PyValueError::new_err("Only explicit SDR sRGB is supported"));
        }
        if zones.len() > u16::MAX as usize / 3 {
            return Err(PyValueError::new_err("Too many zones for one strip frame"));
        }
        let stride = width
            .checked_mul(3)
            .ok_or_else(|| PyValueError::new_err("Invalid width"))?;
        let frame = SdrRgb8Frame::new(pixels.as_bytes(), width, height, stride)
            .map_err(|error| PyValueError::new_err(error.to_string()))?;
        let rects: Vec<_> = zones
            .into_iter()
            .map(|(x, y, width, height)| ZoneRect {
                x,
                y,
                width,
                height,
            })
            .collect();
        let mut samples = vec![ZoneSample::default(); rects.len()];
        // pixels is immutable and kept alive by the bound argument while detached.
        py.detach(|| self.sampler.sample_into(&frame, &rects, &mut samples))
            .map_err(|error| PyValueError::new_err(error.to_string()))?;
        let mut rgb = Vec::with_capacity(samples.len() * 3);
        let mut variance = Vec::with_capacity(samples.len() * 4);
        for sample in samples {
            rgb.extend_from_slice(&sample.srgb);
            variance.extend_from_slice(&(sample.encoded_variance as f32).to_le_bytes());
        }
        Ok((PyBytes::new(py, &rgb), PyBytes::new(py, &variance)))
    }
}

#[pymodule]
fn _nanoleaf_core(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<BoxSampler>()?;
    module.add("ABI_VERSION", 1)?;
    module.add("COMPILER", env!("NANOLEAF_CORE_BUILD_RUSTC"))?;
    Ok(())
}
