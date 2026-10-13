//! Existing best-effort nice policy. Never request a real-time scheduler.
use serde::{Deserialize, Serialize};
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct PriorityStatus {
    pub configured: String,
    pub effective_nice: Option<i32>,
    pub error: Option<String>,
}
pub fn target(mode: &str) -> Option<i32> {
    match mode {
        "high" => Some(-5),
        "very_high" => Some(-10),
        _ => None,
    }
}
pub fn apply(mode: &str) -> PriorityStatus {
    let current = rustix::process::getpriority_process(None).ok();
    let error = target(mode).and_then(|requested| {
        rustix::process::setpriority_process(None, requested.min(current.unwrap_or(requested)))
            .err()
            .map(|e| e.to_string())
    });
    PriorityStatus {
        configured: mode.into(),
        effective_nice: rustix::process::getpriority_process(None).ok(),
        error,
    }
}
#[cfg(test)]
mod tests {
    #[test]
    fn policy_has_only_existing_modes_and_normal_never_changes_priority() {
        assert_eq!(super::target("normal"), None);
        assert_eq!(super::target("unknown"), None);
        assert_eq!(super::target("high"), Some(-5));
        assert_eq!(super::target("very_high"), Some(-10));
        let before = rustix::process::getpriority_process(None).ok();
        let normal = super::apply("normal");
        assert_eq!(normal.effective_nice, before);
        assert!(normal.error.is_none());
    }
}
