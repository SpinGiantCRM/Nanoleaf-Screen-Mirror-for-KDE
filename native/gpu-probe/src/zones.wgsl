// Integer histograms retain every RGB8 pixel. EOTF/variance reduction uses the
// same validated CPU reference afterwards; no GPU floating atomic approximation.
struct Parameters { width: u32, height: u32, stride: u32, count: u32 }
@group(0) @binding(0) var<storage, read> image: array<u32>;
@group(0) @binding(1) var<storage, read> zones: array<vec4<u32>>;
@group(0) @binding(2) var<storage, read_write> result: array<u32>;
@group(0) @binding(3) var<uniform> params: Parameters;
var<workgroup> histogram: array<atomic<u32>, 768>;
fn byte_at(offset: u32) -> u32 {
    return (image[offset / 4u] >> ((offset % 4u) * 8u)) & 255u;
}
@compute @workgroup_size(256)
fn sample(@builtin(workgroup_id) group: vec3<u32>, @builtin(local_invocation_index) lane: u32) {
    for (var i = lane; i < 768u; i += 256u) { atomicStore(&histogram[i], 0u); }
    workgroupBarrier();
    let rect = zones[group.x];
    let pixels = rect.z * rect.w;
    for (var i = lane; i < pixels; i += 256u) {
        let offset = (rect.y + i / rect.z) * params.stride + (rect.x + i % rect.z) * 3u;
        atomicAdd(&histogram[byte_at(offset)], 1u);
        atomicAdd(&histogram[256u + byte_at(offset + 1u)], 1u);
        atomicAdd(&histogram[512u + byte_at(offset + 2u)], 1u);
    }
    workgroupBarrier();
    for (var i = lane; i < 768u; i += 256u) { result[group.x * 768u + i] = atomicLoad(&histogram[i]); }
}
