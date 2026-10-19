// Exact RGB8 channel totals for the detector's forward/reverse 8-pixel grid.
// Only integer additions after the same byte normalization as texture.wgsl.
@group(0) @binding(0) var image: texture_2d<f32>;
@group(0) @binding(1) var<storage, read_write> result: array<vec4<u32>>;
@group(0) @binding(2) var<uniform> params: vec4<u32>; // vertical, start, end, half
var<workgroup> partial: array<vec3<u32>, 256>;
@compute @workgroup_size(256)
fn lines(@builtin(workgroup_id) group: vec3<u32>, @builtin(local_invocation_index) lane: u32) {
    let size = textureDimensions(image);
    let limit = select(size.y, size.x, params.x != 0u);
    let line = select((group.x % params.w) * 8u, limit - 1u - (group.x % params.w) * 8u, group.x >= params.w);
    var sum = vec3<u32>(0u);
    for (var i = params.y + lane; i < params.z; i += 256u) {
        let position = select(vec2<u32>(i, line), vec2<u32>(line, i), params.x != 0u);
        let pixel = textureLoad(image, vec2<i32>(position), 0);
        let rgb = select(vec3<u32>(0u), vec3<u32>(round(clamp(pixel.rgb, vec3<f32>(0.0), vec3<f32>(1.0)) * 255.0)), pixel.a > 0.0);
        sum += rgb;
    }
    partial[lane] = sum;
    workgroupBarrier();
    for (var stride = 128u; stride > 0u; stride /= 2u) {
        if (lane < stride) { partial[lane] += partial[lane + stride]; }
        workgroupBarrier();
    }
    if (lane == 0u) { result[group.x] = vec4<u32>(partial[0], params.z - params.y); }
}
