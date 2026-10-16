use nanoleaf_native::response::{Responses, Sample, WINDOW};

fn sample(ms: f64) -> Sample {
    Sample {
        capture_ms: ms,
        processing_ms: ms / 2.0,
        queue_ms: ms / 4.0,
        usb_ms: ms * 2.0,
        to_write_ms: ms * 3.0,
        to_ack_ms: ms * 4.0,
    }
}

#[test]
fn exact_nearest_rank_tails_include_frames_missed_by_status_polling() {
    let mut responses = Responses::default();
    for ms in (1..=100).rev() {
        responses.record(sample(f64::from(ms)), false);
    }
    // A cached-source clock must never dilute the fresh-source distribution.
    responses.record(sample(0.0), true);
    let result = responses.summary();
    let s = &result.fresh;
    assert_eq!((s.observed, s.samples), (100, 100));
    assert_eq!(s.capture_ms.min, 1.0);
    assert_eq!(s.capture_ms.p50, 50.0);
    assert_eq!(s.capture_ms.p95, 95.0);
    assert_eq!(s.capture_ms.p99, 99.0);
    assert_eq!(s.capture_ms.max, 100.0);
    assert_eq!(s.processing_ms.p95, 47.5);
    assert_eq!(s.queue_ms.p95, 23.75);
    assert_eq!(s.usb_ms.p95, 190.0);
    assert_eq!(s.to_write_ms.p95, 285.0);
    assert_eq!(s.to_ack_ms.p95, 380.0);
    assert_eq!(result.cached.samples, 1);
    assert_eq!(result.cached.capture_ms.max, 0.0);
    assert_eq!(result.rejected_samples, 0);
}

#[test]
fn rolling_storage_is_bounded_and_counts_outlive_the_retained_window() {
    let mut responses = Responses::default();
    responses.record(sample(10_000.0), false);
    for _ in 0..WINDOW {
        responses.record(sample(2.0), false);
        responses.record(sample(3.0), true);
    }
    let result = responses.summary();
    assert_eq!(result.fresh.observed, WINDOW as u64 + 1);
    assert_eq!(result.fresh.samples, WINDOW);
    assert_eq!(result.fresh.capture_ms.max, 2.0);
    assert_eq!(result.cached.observed, WINDOW as u64);
    assert_eq!(result.cached.samples, WINDOW);
    assert_eq!(result.cached.capture_ms.min, 3.0);
    // Snapshots do not consume samples. Reset is explicit for new connections.
    assert_eq!(responses.summary().fresh.samples, WINDOW);
    responses = Responses::default();
    assert_eq!(responses.summary().fresh.observed, 0);
    assert_eq!(responses.summary().cached.samples, 0);
}

#[test]
fn invalid_clocks_do_not_poison_quantiles_and_json_contains_no_payloads() {
    let mut responses = Responses::default();
    for value in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY, -0.1] {
        responses.record(
            Sample {
                queue_ms: value,
                ..sample(1.0)
            },
            false,
        );
    }
    responses.record(
        Sample {
            to_write_ms: 5.0,
            ..sample(1.0)
        },
        false,
    );
    responses.record(sample(0.0), true);
    let result = responses.summary();
    assert_eq!(result.rejected_samples, 5);
    assert_eq!(result.fresh.samples, 0);
    assert_eq!(result.cached.samples, 1);
    let text = serde_json::to_string(&result).unwrap();
    assert!(!text.contains("colors") && !text.contains("profile"));
    assert_eq!(
        serde_json::from_str::<serde_json::Value>(&text).unwrap()["cached"]["to_ack_ms"]["p99"],
        0.0
    );
}

#[test]
fn status_remains_compatible_and_fits_the_bounded_control_reply() {
    use nanoleaf_native::{device::TransactionTimes, service::Status};
    let mut responses = Responses::default();
    responses.record(sample(1.23456789), false);
    responses.record(sample(9.87654321), true);
    let status = Status {
        response_summary: Some(responses.summary()),
        prepared_queue_ms: Some(2.0),
        usb_transaction: Some(TransactionTimes {
            report_write_ms: vec![1.23456789; 25],
            ..Default::default()
        }),
        ..Default::default()
    };
    let mut json = serde_json::to_value(status).unwrap();
    assert!(serde_json::to_vec(&json).unwrap().len() < 16384);
    // A new settings client can read status from the older installed service.
    json.as_object_mut().unwrap().remove("response_summary");
    json.as_object_mut().unwrap().remove("prepared_queue_ms");
    let older: Status = serde_json::from_value(json).unwrap();
    assert!(older.response_summary.is_none() && older.prepared_queue_ms.is_none());
}
