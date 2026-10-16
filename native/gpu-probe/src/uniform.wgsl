// Exact proof over every normalized RGB8 pixel. Hidden RGB at alpha zero is
// black, consistently with texture.wgsl and regions_rgb. No image leaves GPU.
@group(0) @binding(0) var image: texture_2d<f32>;
@group(0) @binding(1) var<storage, read_write> result: array<u32>;
var<workgroup> different: atomic<u32>;
fn rgb8(position: vec2<u32>) -> vec3<u32> {
    let pixel = textureLoad(image, vec2<i32>(position), 0);
    return select(vec3<u32>(0u), vec3<u32>(round(clamp(pixel.rgb, vec3<f32>(0.0), vec3<f32>(1.0)) * 255.0)), pixel.a > 0.0);
}
@compute @workgroup_size(256)
fn uniform(@builtin(workgroup_id) group: vec3<u32>, @builtin(local_invocation_index) lane: u32) {
    if (lane == 0u) { atomicStore(&different, 0u); }
    workgroupBarrier();
    let size = textureDimensions(image);
    let reference = rgb8(vec2<u32>(0u));
    var mismatch = 0u;
    for (var i = group.x * 256u + lane; i < size.x * size.y; i += 256u * 256u) {
        let rgb = rgb8(vec2<u32>(i % size.x, i / size.x));
        let delta = rgb ^ reference;
        mismatch |= delta.r | delta.g | delta.b;
    }
    atomicOr(&different, mismatch);
    workgroupBarrier();
    if (lane == 0u) { result[group.x] = atomicLoad(&different); }
}
