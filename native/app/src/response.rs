//! Bounded software response measurements, never screen colours or calibration.
//! Fresh and cached-source output have separate clocks and separate windows.
use std::collections::VecDeque;

pub const WINDOW: usize = 512;

#[derive(Clone, Copy, Debug)]
pub struct Sample {
    pub capture_ms: f64,
    pub processing_ms: f64,
    /// Parent latest-slot insertion to the start of the USB transaction.
    pub queue_ms: f64,
    pub usb_ms: f64,
    pub to_write_ms: f64,
    pub to_ack_ms: f64,
}
impl Sample {
    fn valid(self) -> bool {
        [
            self.capture_ms,
            self.processing_ms,
            self.queue_ms,
            self.usb_ms,
            self.to_write_ms,
            self.to_ack_ms,
        ]
        .into_iter()
        .all(|v| v.is_finite() && v >= 0.0)
            && self.to_write_ms <= self.to_ack_ms
    }
}

/// Exact nearest-rank percentiles of the retained window, in milliseconds.
#[derive(Clone, Debug, Default, serde::Serialize, serde::Deserialize)]
pub struct Distribution {
    pub min: f64,
    pub p50: f64,
    pub p95: f64,
    pub p99: f64,
    pub max: f64,
}
impl Distribution {
    fn from(mut values: Vec<f64>) -> Self {
        if values.is_empty() {
            return Self::default();
        }
        values.sort_unstable_by(f64::total_cmp);
        let rank = |percent: usize| values[(values.len() * percent).div_ceil(100) - 1];
        Self {
            min: values[0],
            p50: rank(50),
            p95: rank(95),
            p99: rank(99),
            max: values[values.len() - 1],
        }
    }
}

#[derive(Clone, Debug, Default, serde::Serialize, serde::Deserialize)]
pub struct Summary {
    pub observed: u64,
    pub samples: usize,
    pub capture_ms: Distribution,
    pub processing_ms: Distribution,
    pub queue_ms: Distribution,
    pub usb_ms: Distribution,
    pub to_write_ms: Distribution,
    pub to_ack_ms: Distribution,
}
#[derive(Clone, Debug, Default, serde::Serialize, serde::Deserialize)]
pub struct ResponseSummary {
    pub fresh: Summary,
    pub cached: Summary,
    pub rejected_samples: u64,
}
#[derive(Default)]
struct Window {
    samples: VecDeque<Sample>,
    observed: u64,
}
impl Window {
    fn push(&mut self, sample: Sample) {
        if self.samples.len() == WINDOW {
            self.samples.pop_front();
        }
        self.samples.push_back(sample);
        self.observed = self.observed.saturating_add(1);
    }
    fn summary(&self) -> Summary {
        let values = |field: fn(&Sample) -> f64| {
            Distribution::from(self.samples.iter().map(field).collect())
        };
        Summary {
            observed: self.observed,
            samples: self.samples.len(),
            capture_ms: values(|s| s.capture_ms),
            processing_ms: values(|s| s.processing_ms),
            queue_ms: values(|s| s.queue_ms),
            usb_ms: values(|s| s.usb_ms),
            to_write_ms: values(|s| s.to_write_ms),
            to_ack_ms: values(|s| s.to_ack_ms),
        }
    }
}
#[derive(Default)]
pub struct Responses {
    fresh: Window,
    cached: Window,
    rejected: u64,
}
impl Responses {
    pub fn record(&mut self, sample: Sample, cached: bool) {
        if !sample.valid() {
            self.rejected = self.rejected.saturating_add(1);
        } else if cached {
            self.cached.push(sample);
        } else {
            self.fresh.push(sample);
        }
    }
    /// Call at most once a second during mirroring; also flush at Stop/failure.
    pub fn summary(&self) -> ResponseSummary {
        ResponseSummary {
            fresh: self.fresh.summary(),
            cached: self.cached.summary(),
            rejected_samples: self.rejected,
        }
    }
}
