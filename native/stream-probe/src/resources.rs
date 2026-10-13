//! Process-only counters. Excludes compositor, GPU and controller power.
use serde_json::{json, Value};
pub fn snapshot() -> Value {
    let ticks = std::fs::read_to_string("/proc/self/stat")
        .ok()
        .and_then(|s| {
            let fields: Vec<_> = s.rsplit_once(") ")?.1.split_whitespace().collect();
            Some(fields.get(11)?.parse::<u64>().ok()? + fields.get(12)?.parse::<u64>().ok()?)
        });
    let memory = std::fs::read_to_string("/proc/self/smaps_rollup").ok();
    let field = |name: &str| {
        memory.as_ref().and_then(|s| {
            s.lines().find_map(|line| {
                let mut parts = line.split_whitespace();
                (parts.next() == Some(name))
                    .then(|| parts.next()?.parse::<u64>().ok())
                    .flatten()
            })
        })
    };
    json!({"cpu_ticks":ticks,"clock_ticks_per_second":rustix::param::clock_ticks_per_second(),"rss_kib":field("Rss:"),"pss_kib":field("Pss:"),"open_fds":std::fs::read_dir("/proc/self/fd").ok().map(|entries|entries.count())})
}
