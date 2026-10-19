//! Pure setup state: manual geometry stays authoritative and previews use saved settings.
use crate::config::Config;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Step {
    Connect,
    Corners,
    Colours,
    Ready,
}

impl Step {
    pub const ALL: [Self; 4] = [Self::Connect, Self::Corners, Self::Colours, Self::Ready];

    pub fn title(self) -> &'static str {
        match self {
            Self::Connect => "Connect your strip",
            Self::Corners => "Locate the corners",
            Self::Colours => "Check the colours",
            Self::Ready => "Ready to mirror",
        }
    }

    pub fn next(self) -> Option<Self> {
        match self {
            Self::Connect => Some(Self::Corners),
            Self::Corners => Some(Self::Colours),
            Self::Colours => Some(Self::Ready),
            Self::Ready => None,
        }
    }

    pub fn previous(self) -> Option<Self> {
        match self {
            Self::Connect => None,
            Self::Corners => Some(Self::Connect),
            Self::Colours => Some(Self::Corners),
            Self::Ready => Some(Self::Colours),
        }
    }
}

/// Readiness of the physical mapping, independent of optional capture policies.
pub fn needs_setup(config: &Config) -> bool {
    if !(4..=512).contains(&config.device_zone_count) {
        return true;
    }
    let mut anchors = config.anchors();
    anchors.sort_unstable();
    anchors[0] < 0
        || anchors[3] >= config.device_zone_count as i64
        || anchors.windows(2).any(|pair| pair[0] == pair[1])
}

/// Preview uses the service's saved device settings; anchors can still be unknown.
pub fn can_locate(saved: &Config, draft: &Config) -> bool {
    (4..=512).contains(&saved.device_zone_count)
        && saved.device_zone_count == draft.device_zone_count
        && saved.device_vid == draft.device_vid
        && saved.device_pid == draft.device_pid
        && saved.output_channel_order == draft.output_channel_order
        && saved.reverse_zones == draft.reverse_zones
}

/// Finishing setup requires the same policies that the real mirroring path checks.
pub fn ready(config: &Config) -> anyhow::Result<()> {
    crate::pipeline::validate_mirroring(config)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn configured() -> Config {
        let mut config = Config {
            device_zone_count: 48,
            ..Default::default()
        };
        config.calibration.corner_anchor_top_left = 0;
        config.calibration.corner_anchor_top_right = 12;
        config.calibration.corner_anchor_bottom_right = 24;
        config.calibration.corner_anchor_bottom_left = 36;
        config
    }

    #[test]
    fn manual_count_and_four_distinct_in_range_anchors_control_first_run() {
        assert!(needs_setup(&Config::default()));
        let mut config = configured();
        assert!(!needs_setup(&config));
        config.device_zone_count = 12;
        assert!(needs_setup(&config));
        config = configured();
        config.calibration.corner_anchor_bottom_left = 24;
        assert!(needs_setup(&config));
        config = configured();
        config.calibration.corner_anchor_bottom_left = -1;
        assert!(needs_setup(&config));
        config = configured();
        config.device_zone_count = 513;
        assert!(needs_setup(&config));
        // Unsupported capture policy is a readiness issue, not first-run setup.
        config = configured();
        config.capture_backend = "kmsgrab".into();
        assert!(!needs_setup(&config));
        assert!(ready(&config).is_err());
        config = configured();
        config.device_zone_count = 4;
        config.calibration.corner_anchor_top_left = 0;
        config.calibration.corner_anchor_top_right = 1;
        config.calibration.corner_anchor_bottom_right = 2;
        config.calibration.corner_anchor_bottom_left = 3;
        assert!(!needs_setup(&config));
        config.device_zone_count = 3;
        assert!(needs_setup(&config));
    }

    #[test]
    fn previews_require_saved_geometry_but_can_locate_before_corners_are_known() {
        let mut saved = Config {
            device_zone_count: 48,
            ..Default::default()
        };
        let mut draft = saved.clone();
        assert!(can_locate(&saved, &draft));
        assert!(needs_setup(&draft));
        draft.calibration.corner_anchor_top_left = 3;
        assert!(can_locate(&saved, &draft));
        draft.device_zone_count = 24;
        assert!(!can_locate(&saved, &draft));
        draft = saved.clone();
        draft.device_pid = 0x8201;
        assert!(!can_locate(&saved, &draft));
        draft = saved.clone();
        draft.device_vid = 0;
        assert!(!can_locate(&saved, &draft));
        draft = saved.clone();
        draft.output_channel_order = "rgb".into();
        assert!(!can_locate(&saved, &draft));
        draft = saved.clone();
        draft.reverse_zones = true;
        assert!(!can_locate(&saved, &draft));
        draft = saved.clone();
        draft.capture_monitor = "A newly selected screen".into();
        draft.led_calibration_profile_sdr.red_gain = 0.8;
        // LED location previews do not infer or alter source/calibration choices.
        assert!(can_locate(&saved, &draft));
        saved.device_zone_count = 0;
        assert!(!can_locate(&saved, &saved));
    }

    #[test]
    fn only_valid_configuration_can_finish_setup_and_navigation_has_endpoints() {
        assert!(ready(&Config::default()).is_err());
        assert!(ready(&configured()).is_ok());
        assert_eq!(Step::Connect.previous(), None);
        assert_eq!(Step::Ready.next(), None);
        let mut visited = vec![Step::Connect];
        while let Some(next) = visited.last().unwrap().next() {
            assert_eq!(next.previous(), visited.last().copied());
            visited.push(next);
        }
        assert_eq!(visited, Step::ALL);
    }
}
