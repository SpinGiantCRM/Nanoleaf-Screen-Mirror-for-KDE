//! Enumerate KDE's Wayland output names for a single selected capture monitor.
use wayland_client::{
    protocol::{wl_output, wl_registry},
    Connection, Dispatch, QueueHandle,
};
use wayland_protocols::xdg::xdg_output::zv1::client::{zxdg_output_manager_v1, zxdg_output_v1};
#[derive(Default, Clone, Debug)]
pub struct OutputInfo {
    pub name: String,
    pub position: Option<(i32, i32)>,
    pub size: Option<(i32, i32)>,
}
#[derive(Default)]
struct Screens {
    outputs: Vec<wl_output::WlOutput>,
    info: Vec<OutputInfo>,
    manager: Option<zxdg_output_manager_v1::ZxdgOutputManagerV1>,
}
impl Dispatch<wl_registry::WlRegistry, ()> for Screens {
    fn event(
        state: &mut Self,
        registry: &wl_registry::WlRegistry,
        event: wl_registry::Event,
        _: &(),
        _: &Connection,
        qh: &QueueHandle<Self>,
    ) {
        if let wl_registry::Event::Global {
            name,
            interface,
            version,
        } = event
        {
            if interface == "wl_output" {
                let index = state.info.len();
                state.info.push(OutputInfo::default());
                state
                    .outputs
                    .push(registry.bind(name, version.min(4), qh, index));
            } else if interface == "zxdg_output_manager_v1" {
                state.manager = Some(registry.bind(name, version.min(3), qh, ()));
            }
        }
    }
}
impl Dispatch<wl_output::WlOutput, usize> for Screens {
    fn event(
        state: &mut Self,
        _: &wl_output::WlOutput,
        event: wl_output::Event,
        index: &usize,
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        if let wl_output::Event::Name { name } = event {
            state.info[*index].name = name;
        }
    }
}
impl Dispatch<zxdg_output_manager_v1::ZxdgOutputManagerV1, ()> for Screens {
    fn event(
        _: &mut Self,
        _: &zxdg_output_manager_v1::ZxdgOutputManagerV1,
        _: zxdg_output_manager_v1::Event,
        _: &(),
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
    }
}
impl Dispatch<zxdg_output_v1::ZxdgOutputV1, usize> for Screens {
    fn event(
        state: &mut Self,
        _: &zxdg_output_v1::ZxdgOutputV1,
        event: zxdg_output_v1::Event,
        index: &usize,
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        match event {
            zxdg_output_v1::Event::LogicalPosition { x, y } => {
                state.info[*index].position = Some((x, y))
            }
            zxdg_output_v1::Event::LogicalSize { width, height } => {
                state.info[*index].size = Some((width, height))
            }
            zxdg_output_v1::Event::Name { name } => state.info[*index].name = name,
            _ => {}
        }
    }
}
pub fn outputs() -> anyhow::Result<Vec<OutputInfo>> {
    let connection = Connection::connect_to_env()?;
    let mut queue = connection.new_event_queue();
    let qh = queue.handle();
    let _registry = connection.display().get_registry(&qh, ());
    let mut state = Screens::default();
    queue.roundtrip(&mut state)?;
    let mut descriptions = Vec::new();
    if let Some(manager) = &state.manager {
        for (index, output) in state.outputs.iter().enumerate() {
            descriptions.push(manager.get_xdg_output(output, &qh, index));
        }
    }
    queue.roundtrip(&mut state)?;
    Ok(state
        .info
        .into_iter()
        .filter(|o| !o.name.is_empty())
        .collect())
}
pub fn names() -> anyhow::Result<Vec<String>> {
    let mut names: Vec<_> = outputs()?.into_iter().map(|o| o.name).collect();
    names.sort();
    names.dedup();
    Ok(names)
}

/// Verify a single physical output instead of promoting a different saved source.
pub fn selected(
    outputs: &[OutputInfo],
    position: Option<(i32, i32)>,
    size: Option<(i32, i32)>,
    target: &str,
) -> anyhow::Result<String> {
    let matching: Vec<_> = outputs
        .iter()
        .filter(|o| {
            o.position == position
                && o.size == size
                && o.position.is_some()
                && o.size.is_some_and(|(w, h)| w > 0 && h > 0)
        })
        .collect();
    anyhow::ensure!(
        matching.len() == 1 && (target.is_empty() || matching[0].name == target),
        "Choose the configured single monitor in KDE; this shared source is ambiguous or different"
    );
    Ok(matching[0].name.clone())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn portal_source_must_match_one_selected_monitor() {
        let outputs = [
            OutputInfo {
                name: "DP-1".into(),
                position: Some((0, 0)),
                size: Some((2560, 1440)),
            },
            OutputInfo {
                name: "DP-2".into(),
                position: Some((2560, 0)),
                size: Some((1920, 1080)),
            },
        ];
        assert_eq!(
            selected(&outputs, Some((0, 0)), Some((2560, 1440)), "DP-1").unwrap(),
            "DP-1"
        );
        assert!(selected(&outputs, Some((0, 0)), Some((2560, 1440)), "DP-2").is_err());
        assert!(selected(&outputs, Some((0, 0)), Some((4480, 1440)), "").is_err());
        assert!(selected(&outputs, None, None, "").is_err());
        assert!(selected(
            &[outputs[0].clone(), outputs[0].clone()],
            Some((0, 0)),
            Some((2560, 1440)),
            "DP-1"
        )
        .is_err());
    }
}
