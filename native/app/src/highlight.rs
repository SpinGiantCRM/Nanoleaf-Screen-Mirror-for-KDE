//! Exact pixel equality reuse for pure highlight sampling. No hash collisions,
//! skipped pixel coverage, output-history caching or approximate frame reuse.
use nanoleaf_core::sampling::{Error, SdrSampler};
struct Entry {
    pixels: Vec<[u8; 3]>,
    peak: bool,
    result: ([u8; 3], bool),
}
pub struct Cache {
    slots: Vec<Option<Entry>>,
    bytes: usize,
    hits: u64,
    limit: usize,
}
impl Default for Cache {
    fn default() -> Self {
        Self {
            slots: Vec::new(),
            bytes: 0,
            hits: 0,
            limit: 16 * 1024 * 1024,
        }
    }
}
impl Cache {
    pub fn clear(&mut self) {
        self.slots.clear();
        self.bytes = 0;
        self.hits = 0;
    }
    pub fn reset(&mut self, count: usize) {
        if self.slots.len() != count {
            self.clear();
            self.slots.resize_with(count, || None);
        }
    }
    pub fn statistics(&self) -> (usize, u64) {
        (self.bytes, self.hits)
    }
    pub fn sample(
        &mut self,
        sampler: &SdrSampler,
        index: usize,
        pixels: Vec<[u8; 3]>,
        peak: bool,
    ) -> Result<([u8; 3], bool), Error> {
        let slot = self.slots.get_mut(index).ok_or(Error::OutputLength)?;
        if let Some(entry) = slot.as_ref() {
            if entry.peak == peak && entry.pixels == pixels {
                self.hits += 1;
                return Ok(entry.result);
            }
        }
        let result = sampler.highlight_mean(&pixels, peak)?;
        if let Some(previous) = slot.take() {
            self.bytes -= previous.pixels.capacity() * 3;
        }
        let bytes = pixels.capacity().saturating_mul(3);
        if bytes <= self.limit.saturating_sub(self.bytes) {
            *slot = Some(Entry {
                pixels,
                peak,
                result,
            });
            self.bytes += bytes;
        }
        Ok(result)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn cache_checks_exact_pixels_mode_and_bounds_retained_capacity() {
        let sampler = SdrSampler::default();
        let mut cache = Cache {
            limit: 96,
            ..Default::default()
        };
        cache.reset(3);
        cache.sample(&sampler, 0, vec![[128; 3]; 32], true).unwrap();
        assert_eq!(cache.statistics(), (96, 0));
        cache.sample(&sampler, 0, vec![[128; 3]; 32], true).unwrap();
        assert_eq!(cache.statistics(), (96, 1));
        cache
            .sample(&sampler, 0, vec![[128; 3]; 32], false)
            .unwrap();
        assert_eq!(cache.statistics(), (96, 1));
        assert_eq!(
            cache
                .sample(&sampler, 0, vec![[129; 3]; 32], false)
                .unwrap()
                .0,
            [129; 3]
        );
        cache.sample(&sampler, 1, vec![[64; 3]; 32], true).unwrap();
        assert_eq!(cache.statistics().0, 96);
        let mut spare = Vec::with_capacity(33);
        spare.push([255; 3]);
        cache.sample(&sampler, 0, spare, true).unwrap();
        assert_eq!(cache.statistics().0, 0);
        cache.clear();
        assert_eq!(cache.statistics(), (0, 0));
    }
}
