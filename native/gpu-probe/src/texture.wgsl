// Integer histograms retain every RGB8 pixel. EOTF/variance reduction uses the
// same validated CPU reference afterwards; no GPU floating atomic approximation.
struct Parameters { width: u32, height: u32, stride: u32, count: u32 }
@group(0) @binding(0) var image: texture_2d<f32>;
@group(0) @binding(1) var<storage, read> zones: array<vec4<u32>>;
@group(0) @binding(2) var<storage, read_write> result: array<u32>;
@group(0) @binding(3) var<uniform> params: Parameters;
var<workgroup> histogram: array<atomic<u32>, 768>;
@compute @workgroup_size(256)
fn sample(@builtin(workgroup_id) group: vec3<u32>, @builtin(local_invocation_index) lane: u32) {
    if (group.x >= params.count) { return; }
    for (var i = lane; i < 768u; i += 256u) { atomicStore(&histogram[i], 0u); }
    workgroupBarrier();
    let rect = zones[group.x];
    let pixels = rect.z * rect.w;
    for (var i = lane; i < pixels; i += 256u) {
        let pixel = textureLoad(image, vec2<i32>(i32(rect.x + i % rect.z), i32(rect.y + i / rect.z)), 0);
        let rgb = select(vec3<u32>(0u), vec3<u32>(round(clamp(pixel.rgb, vec3<f32>(0.0), vec3<f32>(1.0)) * 255.0)), pixel.a > 0.0);
        atomicAdd(&histogram[rgb.r], 1u);
        atomicAdd(&histogram[256u + rgb.g], 1u);
        atomicAdd(&histogram[512u + rgb.b], 1u);
    }
    workgroupBarrier();
    for (var i = lane; i < 768u; i += 256u) { result[group.x * 768u + i] = atomicLoad(&histogram[i]); }
}
