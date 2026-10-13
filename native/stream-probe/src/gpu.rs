use anyhow::{ensure, Result};
use std::{
    future::Future,
    sync::Arc,
    task::{Poll, Wake, Waker},
    time::Duration,
};
struct ThreadWake(std::thread::Thread);
impl Wake for ThreadWake {
    fn wake(self: Arc<Self>) {
        self.0.unpark();
    }
}
pub fn wait<T>(future: impl Future<Output = T>) -> T {
    let waker = Waker::from(Arc::new(ThreadWake(std::thread::current())));
    let mut context = std::task::Context::from_waker(&waker);
    let mut future = std::pin::pin!(future);
    loop {
        match future.as_mut().poll(&mut context) {
            Poll::Ready(v) => return v,
            Poll::Pending => std::thread::park_timeout(Duration::from_millis(100)),
        }
    }
}
struct GpuLog;
static GPU_LOG: GpuLog = GpuLog;
impl log::Log for GpuLog {
    fn enabled(&self, metadata: &log::Metadata<'_>) -> bool {
        metadata.level() <= log::Level::Warn && metadata.target().starts_with("wgpu")
    }
    fn log(&self, record: &log::Record<'_>) {
        if self.enabled(record.metadata()) {
            eprintln!("{} {}: {}", record.level(), record.target(), record.args());
        }
    }
    fn flush(&self) {}
}
pub fn prepare() -> Result<(wgpu::Device, wgpu::Queue, serde_json::Value)> {
    let _ = log::set_logger(&GPU_LOG);
    log::set_max_level(log::LevelFilter::Warn);
    let flags = if std::env::var_os("NANOLEAF_VULKAN_VALIDATE").is_some() {
        wgpu::InstanceFlags::VALIDATION | wgpu::InstanceFlags::DEBUG
    } else {
        wgpu::InstanceFlags::empty()
    };
    let instance = wgpu::Instance::new(wgpu::InstanceDescriptor {
        backends: wgpu::Backends::VULKAN,
        flags,
        ..wgpu::InstanceDescriptor::new_without_display_handle()
    });
    let adapter = wait(instance.request_adapter(&wgpu::RequestAdapterOptions {
        power_preference: wgpu::PowerPreference::HighPerformance,
        ..Default::default()
    }))?;
    let info = adapter.get_info();
    ensure!(
        info.device_type != wgpu::DeviceType::Cpu,
        "Hardware Vulkan required"
    );
    let (device, queue) = nanoleaf_linux_gpu::create_device(&adapter)?;
    let bgra = nanoleaf_linux_gpu::modifiers(&device, wgpu::TextureFormat::Bgra8Unorm)?;
    let rgba = nanoleaf_linux_gpu::modifiers(&device, wgpu::TextureFormat::Rgba8Unorm)?;
    Ok((
        device,
        queue,
        serde_json::json!({"name":info.name,"driver":info.driver,"driver_info":info.driver_info,"vendor":info.vendor,"bgra_modifiers":bgra,"rgba_modifiers":rgba}),
    ))
}
