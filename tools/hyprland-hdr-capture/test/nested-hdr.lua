-- nested HDR test: one output in PQ HDR mode, like the real desktop (forced, the nested output has no EDID)
hl.monitor({ output = "", mode = "preferred", position = "0x0", scale = 1, bitdepth = 10, cm = "hdr",
             supports_wide_color = 1, supports_hdr = 1,
             sdr_max_luminance = 203, max_luminance = 10000, sdr_min_luminance = 0, min_luminance = 0 })
