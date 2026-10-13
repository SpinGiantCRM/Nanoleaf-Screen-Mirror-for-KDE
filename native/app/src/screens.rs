//! Enumerate KDE's Wayland output names for a single selected capture monitor.
use wayland_client::{
    protocol::{wl_output, wl_registry},
    Connection, Dispatch, QueueHandle,
};
#[derive(Default)]
struct Screens {
    outputs: Vec<wl_output::WlOutput>,
    names: Vec<String>,
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
                state
                    .outputs
                    .push(registry.bind(name, version.min(4), qh, ()));
            }
        }
    }
}
impl Dispatch<wl_output::WlOutput, ()> for Screens {
    fn event(
        state: &mut Self,
        _: &wl_output::WlOutput,
        event: wl_output::Event,
        _: &(),
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        if let wl_output::Event::Name { name } = event {
            state.names.push(name);
        }
    }
}
pub fn names() -> anyhow::Result<Vec<String>> {
    let connection = Connection::connect_to_env()?;
    let mut queue = connection.new_event_queue();
    let qh = queue.handle();
    let _registry = connection.display().get_registry(&qh, ());
    let mut state = Screens::default();
    queue.roundtrip(&mut state)?;
    queue.roundtrip(&mut state)?;
    state.names.sort();
    state.names.dedup();
    Ok(state.names)
}
