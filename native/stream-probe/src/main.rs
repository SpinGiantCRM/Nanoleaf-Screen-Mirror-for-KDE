//! Bounded permission-mediated stream experiment. No configuration or USB writes.
mod application;
mod frame;
mod gpu;
mod permission;
mod portal;
mod resources;
use anyhow::{ensure, Context, Result};
use nanoleaf_core::sampling::{SdrRgb8Frame, SdrSampler, ZoneRect};
use nanoleaf_vulkan_probe::VulkanSampler;
use pipewire::{self as pw, properties::properties, spa};
use spa::{
    param::{
        format::{FormatProperties, MediaSubtype, MediaType},
        video::{VideoFormat, VideoInfoRaw},
    },
    pod::Pod,
};
use std::{
    cell::RefCell,
    rc::Rc,
    time::{Duration, Instant},
};
// SPA's append-only buffers ABI assigns metaType key 7. Older PipeWire headers
// (including Ubuntu 24.04) omit its Rust binding. Keep the same wire property:
// https://gitlab.freedesktop.org/pipewire/pipewire/-/blob/master/spa/include/spa/param/buffers.h
const PARAM_BUFFERS_META_TYPE: u32 = 7;
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
enum Mode {
    #[default]
    Cpu,
    Upload,
    Dma,
}
#[derive(Default)]
struct State {
    format: Option<VideoInfoRaw>,
    sampler: SdrSampler,
    frames: u64,
    dropped: u64,
    discarded: u64,
    corrupt_or_empty: u64,
    sequence: Option<u64>,
    rgb: Vec<u8>,
    gpu: Option<VulkanSampler>,
    zones: Vec<ZoneRect>,
    timings: Vec<serde_json::Value>,
    errors: Vec<String>,
    format_info: serde_json::Value,
    mode: Mode,
    texture: Option<nanoleaf_linux_gpu::DmaSampler>,
    device: Option<(wgpu::Device, wgpu::Queue)>,
    adapter: serde_json::Value,
    layout: Option<(usize, usize)>,
    application: Option<application::Application>,
}
fn zones(width: usize, height: usize) -> Vec<ZoneRect> {
    let mut result = Vec::new();
    for i in 0..12 {
        for (x, y, w, h) in [
            (i * width / 12, 0, width / 12, height / 14),
            (0, i * height / 12, width / 14, height / 12),
            (
                i * width / 12,
                height - height / 14,
                width / 12,
                height / 14,
            ),
            (width - width / 14, i * height / 12, width / 14, height / 12),
        ] {
            result.push(ZoneRect {
                x: x as i64,
                y: y as i64,
                width: w as i64,
                height: h as i64,
            });
        }
    }
    result
}
fn process(buffer: &mut pw::buffer::Buffer<'_>, state: &mut State) -> Result<()> {
    let started = Instant::now();
    let format = state.format.context("No negotiated video format")?;
    if state.application.is_some() {
        ensure!(
            (format.transfer_function() == 0
                || format.transfer_function() == spa::sys::SPA_VIDEO_TRANSFER_SRGB)
                && (format.color_primaries() == 0
                    || format.color_primaries() == spa::sys::SPA_VIDEO_COLOR_PRIMARIES_BT709)
                && (format.color_range() == 0
                    || format.color_range() == spa::sys::SPA_VIDEO_COLOR_RANGE_0_255)
                && (format.color_matrix() == 0
                    || format.color_matrix() == spa::sys::SPA_VIDEO_COLOR_MATRIX_RGB),
            "Stream metadata contradicts the verified sRGB contract"
        );
    }

    let header = buffer.find_meta::<spa::buffer::meta::MetaHeader>().cloned();
    if let Some(h) = &header {
        ensure!(
            !h.flags().intersects(
                spa::buffer::meta::MetaHeaderFlags::CORRUPTED
                    | spa::buffer::meta::MetaHeaderFlags::GAP
            ),
            "Corrupt/gap frame"
        );
        if let Some(previous) = state.sequence {
            if h.seq() > previous {
                state.dropped += h.seq().saturating_sub(previous + 1);
            }
        }
        state.sequence = Some(h.seq());
    }
    if let Some(crop) = buffer.find_meta::<spa::buffer::meta::MetaVideoCrop>() {
        if crop.meta_region().is_valid() {
            let r = crop.meta_region();
            ensure!(
                r.position().x == 0
                    && r.position().y == 0
                    && r.size().width == format.size().width
                    && r.size().height == format.size().height,
                "Cropped video requires explicit zone remapping"
            );
        }
    }
    if state.mode == Mode::Dma {
        return process_dma(buffer, state, format, header, started);
    }
    let packing = match format.format() {
        VideoFormat::BGRA => frame::Packing::Bgra,
        VideoFormat::BGRx => frame::Packing::Bgrx,
        VideoFormat::RGBA => frame::Packing::Rgba,
        VideoFormat::RGBx => frame::Packing::Rgbx,
        _ => anyhow::bail!("Unsupported packed RGB stream"),
    };
    let width = format.size().width as usize;
    let height = format.size().height as usize;
    let datas = buffer.datas_mut();
    ensure!(datas.len() == 1, "Expected one packed memory plane");
    let data = &mut datas[0];
    ensure!(
        matches!(
            data.type_(),
            spa::buffer::DataType::MemPtr | spa::buffer::DataType::MemFd
        ),
        "DMA-BUF is not CPU-linear memory; cannot use mapped RGB path"
    );
    ensure!(
        !data
            .chunk()
            .flags()
            .contains(spa::buffer::ChunkFlags::CORRUPTED),
        "Corrupt chunk"
    );
    let layout = frame::Layout {
        width,
        height,
        stride: data.chunk().stride(),
        offset: data.chunk().offset() as usize,
        size: data.chunk().size() as usize,
        packing,
        premultiplied: format
            .flags()
            .contains(spa::param::video::VideoFlags::PREMULTIPLIED_ALPHA),
    };
    let memory_kind = format!("{:?}", data.type_());
    frame::rgb(
        data.data().context("Stream frame is not mapped")?,
        layout,
        &mut state.rgb,
    )?;
    let decode_ms = started.elapsed().as_secs_f64() * 1000.0;
    if state.layout != Some((width, height)) {
        state.zones = zones(width, height);
        state.gpu = if state.mode == Mode::Upload {
            Some(VulkanSampler::new(width, height, width * 3, &state.zones)?)
        } else {
            None
        };
        state.layout = Some((width, height));
    }
    let cpu = Instant::now();
    let view = SdrRgb8Frame::new(&state.rgb, width, height, width * 3)?;
    let reference: Vec<_> = state
        .zones
        .iter()
        .map(|&z| state.sampler.sample_zone(&view, z))
        .collect();
    let cpu_ms = cpu.elapsed().as_secs_f64() * 1000.0;
    let gpu = if let Some(gpu) = &state.gpu {
        let (actual, timing) = gpu.sample(&state.rgb)?;
        for (a, b) in actual.iter().zip(&reference) {
            ensure!(
                a.srgb == b.srgb
                    && a.linear_rgb == b.linear_rgb
                    && a.encoded_variance == b.encoded_variance
                    && a.pixel_count == b.pixel_count,
                "CPU/Vulkan colour parity failure"
            );
        }
        Some(timing)
    } else {
        None
    };
    state.frames += 1;
    state.timings.push(serde_json::json!({"sequence":header.as_ref().map(|h|h.seq()),"pts_age_ms":pts_age(header.as_ref()),"pts_ns":header.as_ref().map(|h|h.pts()),"memory":memory_kind,"decode_ms":decode_ms,"cpu_sampling_ms":cpu_ms,"vulkan":gpu,"colour_comparisons":if state.mode == Mode::Upload{state.zones.len()}else{0},"callback_ms":started.elapsed().as_secs_f64()*1000.0}));
    Ok(())
}
fn pts_age(header: Option<&spa::buffer::meta::MetaHeader>) -> Option<f64> {
    let pts = header?.pts();
    if pts < 0 {
        return None;
    }
    let time = rustix::time::clock_gettime(rustix::time::ClockId::Monotonic);
    let now = time.tv_sec as i128 * 1_000_000_000 + time.tv_nsec as i128;
    let age = now - pts as i128;
    if !(0..10_000_000_000).contains(&age) {
        return None;
    }
    Some(age as f64 / 1_000_000.0)
}
fn process_dma(
    buffer: &mut pw::buffer::Buffer<'_>,
    state: &mut State,
    format: VideoInfoRaw,
    header: Option<spa::buffer::meta::MetaHeader>,
    started: Instant,
) -> Result<()> {
    let (width, height) = (format.size().width, format.size().height);
    if state.layout != Some((width as usize, height as usize)) {
        state.zones = if let Some(app) = &state.application {
            app.zones(width as usize, height as usize)?
        } else {
            zones(width as usize, height as usize)
        };
        let (device, queue) = state.device.as_ref().context("Vulkan device unavailable")?;
        state.texture = Some(nanoleaf_linux_gpu::DmaSampler::new(
            device.clone(),
            queue.clone(),
            width,
            height,
            &state.zones,
        )?);
        state.layout = Some((width as usize, height as usize));
    }
    let sampler = state.texture.as_mut().context("No GPU texture sampler")?;
    let diagnostic = if let Some(app) = &state.application {
        app.needs_pixels(width as usize, height as usize)
    } else {
        state.frames.is_multiple_of(30)
    };
    let (sampled, bounds) = if let Some(app) = state
        .application
        .as_ref()
        .filter(|a| !a.needs_pixels(width as usize, height as usize))
    {
        sampler.plan_sample(buffer, format, app.parity(), |reader| {
            app.plan(width as usize, height as usize, reader)
        })?
    } else {
        (sampler.sample(buffer, format, diagnostic)?, None)
    };
    let mut comparisons = 0;
    if let Some(rgb) = sampled
        .diagnostic_rgb
        .as_ref()
        .filter(|_| state.application.is_none())
    {
        let view = SdrRgb8Frame::new(rgb, width as usize, height as usize, width as usize * 3)?;
        let cpu = SdrSampler::default();
        for (a, &zone) in sampled.samples.iter().zip(&state.zones) {
            let b = cpu.sample_zone(&view, zone);
            ensure!(
                a.srgb == b.srgb
                    && a.linear_rgb == b.linear_rgb
                    && a.encoded_variance == b.encoded_variance
                    && a.pixel_count == b.pixel_count,
                "Imported DMA-BUF CPU/Vulkan parity failure"
            );
            comparisons += 1;
        }
    }
    if let Some(app) = &mut state.application {
        app.frame(
            width as usize,
            height as usize,
            sampled,
            bounds,
            header.as_ref(),
            started,
        )?;
        state.frames += 1;
        return Ok(());
    }
    let timings = sampled.timings;
    state.frames += 1;
    state.timings.push(serde_json::json!({"sequence":header.as_ref().map(|h|h.seq()),"pts_ns":header.as_ref().map(|h|h.pts()),"pts_age_ms":pts_age(header.as_ref()),"memory":"DMA-BUF","vulkan":timings,"diagnostic_full_readback":diagnostic,"colour_comparisons":comparisons,"callback_ms":started.elapsed().as_secs_f64()*1000.0}));
    Ok(())
}
fn main() -> Result<()> {
    // This is an isolated capture executable. A panic must not unwind and
    // requeue a producer buffer while GPU work might still be pending.
    std::panic::set_hook(Box::new(|info| {
        eprintln!("Capture worker panicked: {info}");
        std::process::exit(2)
    }));
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.first().is_some_and(|a| a == "--worker") {
        ensure!(
            args.len() == 1,
            "Worker takes configuration through private stdin"
        );
        return application::run();
    }
    ensure!(
        args.len() <= 1,
        "Usage: nanoleaf-stream-probe [--gpu-upload|--dma-buf|--suite]"
    );
    let modes = match args.first().map(String::as_str) {
        None => vec![Mode::Cpu],
        Some("--gpu-upload") => vec![Mode::Upload],
        Some("--dma-buf") => vec![Mode::Dma],
        Some("--suite") => vec![Mode::Cpu, Mode::Upload, Mode::Dma],
        _ => anyhow::bail!("Unknown probe option"),
    };
    let prepared = if modes.contains(&Mode::Dma) {
        Some(gpu::prepare()?)
    } else {
        None
    };
    if let Some((_, _, info)) = &prepared {
        ensure!(
            info["bgra_modifiers"]
                .as_array()
                .is_some_and(|m| !m.is_empty()),
            "No importable one-plane BGRA DMA-BUF modifiers"
        );
    }
    let permission = Instant::now();
    let (session, first_fd) = portal::Session::open()?;
    let permission_ms = permission.elapsed().as_secs_f64() * 1000.0;
    let mut first_fd = Some(first_fd);
    let mut results = Vec::new();
    let mut failed = false;
    for mode in modes {
        let fd = if let Some(fd) = first_fd.take() {
            fd
        } else {
            session.remote()?
        };
        let result = run(&session, fd, mode, prepared.as_ref())?;
        failed |= !result["errors"].as_array().is_some_and(Vec::is_empty)
            || result["frames"].as_u64() == Some(0);
        results.push(result);
    }
    println!(
        "{}",
        serde_json::json!({"scope":"Single-monitor portal/PipeWire probe; no USB/config writes or saved images. No native HDR claim. DMA-BUF diagnostics explicitly include full readback; regular GPU sampling does not.","permission_ms":permission_ms,"portal_size":session.size,"phases":results})
    );
    ensure!(!failed, "Stream probe failed or produced no valid frames");
    Ok(())
}
fn run(
    session: &portal::Session,
    fd: std::os::fd::OwnedFd,
    mode: Mode,
    prepared: Option<&(wgpu::Device, wgpu::Queue, serde_json::Value)>,
) -> Result<serde_json::Value> {
    run_application(session, fd, mode, prepared, None)
}
fn run_application(
    session: &portal::Session,
    fd: std::os::fd::OwnedFd,
    mode: Mode,
    prepared: Option<&(wgpu::Device, wgpu::Queue, serde_json::Value)>,
    application: Option<application::Application>,
) -> Result<serde_json::Value> {
    pw::init();
    let mainloop = pw::main_loop::MainLoopRc::new(None)?;
    let context = pw::context::ContextRc::new(&mainloop, None)?;
    let core = context.connect_fd_rc(fd, None)?;
    let mut properties = properties! {
        *pw::keys::MEDIA_TYPE => "Video", *pw::keys::MEDIA_CATEGORY => "Capture", *pw::keys::MEDIA_ROLE => "Screen",
        *pw::keys::NODE_DONT_RECONNECT => "true",
    };
    if let Some(serial) = &session.serial {
        properties.insert(*pw::keys::TARGET_OBJECT, serial.as_str());
    }
    let stream = pw::stream::StreamBox::new(&core, "Nanoleaf native capture probe", properties)?;
    let maximum_fps = application.as_ref().map(|a| a.config.fps).unwrap_or(30);
    let shared = Rc::new(RefCell::new(State {
        mode,
        application,
        device: prepared.map(|(d, q, _)| (d.clone(), q.clone())),
        adapter: prepared.map(|(_, _, i)| i.clone()).unwrap_or_default(),
        ..Default::default()
    }));
    let state = shared.clone();
    let failed = shared.clone();
    let core_listener = core
        .add_listener_local()
        .error(move |_, _, code, message| {
            let mut state = failed.borrow_mut();
            if state.errors.len() < 16 {
                state
                    .errors
                    .push(format!("PipeWire connection failed ({code}): {message}"));
            }
        })
        .register();
    let _listener=stream.add_local_listener_with_user_data(state)
        .state_changed(|_,state,old,new| {
            if let pw::stream::StreamState::Error(error)=new {state.borrow_mut().errors.push(error);}
            else if matches!(new,pw::stream::StreamState::Unconnected) && matches!(old,pw::stream::StreamState::Streaming | pw::stream::StreamState::Paused) {state.borrow_mut().errors.push("Screen sharing ended".into());}
        })
        .param_changed(|_,state,id,param| {
            if id!=spa::param::ParamType::Format.as_raw(){return;}
            let Some(param)=param else {state.borrow_mut().format=None;return;};
            let mut state=state.borrow_mut();
            let mut format=VideoInfoRaw::default();
            match format.parse(param) {
                Ok(_)=>{
                    state.format_info=serde_json::json!({"format":format!("{:?}",format.format()),"width":format.size().width,"height":format.size().height,"modifier":format.modifier(),"flags":format!("{:?}",format.flags()),"color_range":format.color_range(),"color_matrix":format.color_matrix(),"transfer_function":format.transfer_function(),"color_primaries":format.color_primaries()});
                    // Only raw values are compared here, not interpreted as LED colours.
                    state.format=Some(format);
                },Err(error)=>state.errors.push(format!("Invalid video format: {error:?}")),
            }
        })
        .process(|stream,state| {
            let mut state=state.borrow_mut();
            let Some(mut newest)=stream.dequeue_buffer() else {return;};
            // Bound drain work even if a producer is running much faster than us.
            for _ in 0..16 {
                let Some(next)=stream.dequeue_buffer() else {break;};
                newest=next;
                state.discarded+=1;
            }
            let bad_header=newest.find_meta::<spa::buffer::meta::MetaHeader>().is_some_and(|h|h.flags().intersects(spa::buffer::meta::MetaHeaderFlags::CORRUPTED | spa::buffer::meta::MetaHeaderFlags::GAP));
            let datas=newest.datas_mut();
            let bad_chunk=datas.first().is_none_or(|d|d.as_raw().chunk.is_null() || d.chunk().flags().contains(spa::buffer::ChunkFlags::CORRUPTED) || d.chunk().size()==0 || d.chunk().stride()==0);
            if bad_header || bad_chunk {state.corrupt_or_empty+=1;return;}
            if let Err(error)=process(&mut newest,&mut state) {
                if state.errors.len()<16 {state.errors.push(error.to_string());}
            }
        }).register()?;
    let format = spa::pod::object!(
        spa::utils::SpaTypes::ObjectParamFormat,
        spa::param::ParamType::EnumFormat,
        spa::pod::property!(FormatProperties::MediaType, Id, MediaType::Video),
        spa::pod::property!(FormatProperties::MediaSubtype, Id, MediaSubtype::Raw),
        spa::pod::property!(
            FormatProperties::VideoFormat,
            Choice,
            Enum,
            Id,
            VideoFormat::BGRA,
            VideoFormat::BGRA,
            VideoFormat::BGRx,
            VideoFormat::RGBA,
            VideoFormat::RGBx
        ),
        spa::pod::property!(
            FormatProperties::VideoMaxFramerate,
            Choice,
            Range,
            Fraction,
            spa::utils::Fraction {
                num: maximum_fps,
                denom: 1
            },
            spa::utils::Fraction { num: 0, denom: 1 },
            spa::utils::Fraction {
                num: maximum_fps,
                denom: 1
            }
        ),
    );
    let mut formats = vec![format];
    if mode == Mode::Dma {
        let info = &prepared.context("DMA device missing")?.2;
        let modifiers: Vec<i64> = info["bgra_modifiers"]
            .as_array()
            .context("No modifiers")?
            .iter()
            .map(|v| v.as_u64().unwrap() as i64)
            .collect();
        let mut dma = formats[0].clone();
        dma.properties
            .retain(|p| p.key != FormatProperties::VideoFormat.as_raw());
        dma.properties.push(spa::pod::Property::new(
            FormatProperties::VideoFormat.as_raw(),
            spa::pod::Value::Id(spa::utils::Id(VideoFormat::BGRA.as_raw())),
        ));
        dma.properties.push(spa::pod::Property {
            key: FormatProperties::VideoModifier.as_raw(),
            flags: spa::pod::PropertyFlags::MANDATORY | spa::pod::PropertyFlags::DONT_FIXATE,
            value: spa::pod::Value::Choice(spa::pod::ChoiceValue::Long(spa::utils::Choice(
                spa::utils::ChoiceFlags::empty(),
                spa::utils::ChoiceEnum::Enum {
                    default: modifiers[0],
                    alternatives: modifiers,
                },
            ))),
        });
        formats = vec![dma]; // Probe fails rather than disguising SHM fallback as DMA.
    }
    // Restrict the pilot to one image plane and implicit synchronization. Explicit
    // SyncTimeline streams need a different acquire/release implementation.
    formats.push(spa::pod::Object {
        type_: spa::utils::SpaTypes::ObjectParamBuffers.as_raw(),
        id: spa::param::ParamType::Buffers.as_raw(),
        properties: vec![
            spa::pod::Property::new(spa::sys::SPA_PARAM_BUFFERS_blocks, spa::pod::Value::Int(1)),
            spa::pod::Property::new(PARAM_BUFFERS_META_TYPE, spa::pod::Value::Int(0)),
            spa::pod::Property::new(
                spa::sys::SPA_PARAM_BUFFERS_dataType,
                spa::pod::Value::Int(if mode == Mode::Dma {
                    1 << spa::sys::SPA_DATA_DmaBuf
                } else {
                    1 << spa::sys::SPA_DATA_MemFd
                }),
            ),
        ],
    });
    formats.push(spa::pod::Object {
        type_: spa::utils::SpaTypes::ObjectParamMeta.as_raw(),
        id: spa::param::ParamType::Meta.as_raw(),
        properties: vec![
            spa::pod::Property::new(
                spa::sys::SPA_PARAM_META_type,
                spa::pod::Value::Id(spa::utils::Id(spa::sys::SPA_META_Header)),
            ),
            spa::pod::Property::new(
                spa::sys::SPA_PARAM_META_size,
                spa::pod::Value::Int(std::mem::size_of::<spa::sys::spa_meta_header>() as i32),
            ),
        ],
    });
    let serialized: Vec<Vec<u8>> = formats
        .into_iter()
        .map(|f| {
            spa::pod::serialize::PodSerializer::serialize(
                std::io::Cursor::new(Vec::new()),
                &spa::pod::Value::Object(f),
            )
            .map(|s| s.0.into_inner())
        })
        .collect::<std::result::Result<_, _>>()?;
    let mut params: Vec<_> = serialized
        .iter()
        .map(|p| Pod::from_bytes(p).context("Invalid format pod"))
        .collect::<Result<_>>()?;
    stream.connect(
        spa::utils::Direction::Input,
        if session.serial.is_none() {
            Some(session.node)
        } else {
            None
        },
        pw::stream::StreamFlags::AUTOCONNECT | pw::stream::StreamFlags::MAP_BUFFERS,
        &mut params,
    )?;
    let resources_before = resources::snapshot();
    let started = Instant::now();
    while shared
        .borrow()
        .application
        .as_ref()
        .map(|a| !a.cancelled())
        .unwrap_or_else(|| started.elapsed() < Duration::from_secs(8))
    {
        mainloop
            .loop_()
            .iterate(pw::loop_::Timeout::Finite(Duration::from_millis(100)));
        if session.closed() {
            shared
                .borrow_mut()
                .errors
                .push("Screen-sharing permission ended".into());
            break;
        }
        if !shared.borrow().errors.is_empty() {
            break;
        }
    }
    stream.disconnect()?;
    let resources_active = resources::snapshot();
    let state = shared.borrow();
    let mut result = serde_json::json!({"mode":format!("{mode:?}"),"duration_ms":started.elapsed().as_secs_f64()*1000.0,"format":state.format_info,"frames":state.frames,"sequence_gaps":state.dropped,"discarded_buffers":state.discarded,"corrupt_or_empty_buffers":state.corrupt_or_empty,"adapter":state.adapter,"timings":state.timings,"errors":state.errors});
    result["resources_before"] = resources_before;
    result["resources_active"] = resources_active;
    drop(state);
    drop(_listener);
    drop(stream);
    drop(shared);
    drop(core_listener);
    drop(core);
    drop(context);
    drop(mainloop);
    if let Some((device, _, _)) = prepared {
        let _ = device.poll(wgpu::PollType::Poll);
    }
    result["resources_after_close"] = resources::snapshot();
    Ok(result)
}
