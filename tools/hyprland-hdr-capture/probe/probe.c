// nanoleaf-hdr-probe: capture one frame of an output through
// ext-image-copy-capture-v1 into a 10-bit XBGR2101010 buffer and print
// numbers only (no image is saved). Used to check the nanoleaf-hdr plugin.
//
//   nanoleaf-hdr-probe [--output NAME] [--patch X,Y,W,H]... [--raw FILE]
//
// --raw FILE also saves the frame: FILE gets the raw pixels (height rows of
// `stride` bytes, little-endian XBGR2101010, R in the low 10 bits) and
// FILE.json describes them. Both are written mode 0600 via a temporary file and
// rename. --raw only accepts a frame the nanoleaf-hdr plugin delivered as PQ:
//   exit 0  saved (and statistics printed)
//   exit 1  capture or I/O failure (including no frame within 3 s)
//   exit 2  usage
//   exit 3  the plugin is not loaded or the output is not a 10-bit PQ output
//   exit 4  no HDR frame arrived (only Hyprland's SDR conversion)
//
// Values are reported as 10-bit codes and as nits assuming SMPTE ST 2084 (PQ)
// encoding. Only trust the nits column when `hyprctl nanoleafhdr` lists the
// output under "pq_outputs" and the plugin is armed; without the plugin the
// buffer holds sRGB, and the nits column is meaningless.

#define _GNU_SOURCE
#include <errno.h>
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <fcntl.h>
#include <poll.h>
#include <sys/stat.h>
#include <unistd.h>

#include <wayland-client.h>

#include "ext-image-capture-source-v1-client-protocol.h"
#include "ext-image-copy-capture-v1-client-protocol.h"

#define FMT_XBGR2101010 0x30334258u /* 'XB30' */
#define MAX_PATCHES 32

struct output {
    struct wl_output* wl;
    char              name[64];
};

static struct wl_shm*                                    g_shm;
static struct ext_output_image_capture_source_manager_v1* g_sourceManager;
static struct ext_image_copy_capture_manager_v1*         g_copyManager;
static struct output                                     g_outputs[16];
static int                                               g_outputCount;

static uint32_t g_width, g_height;
static bool     g_hasTenBit, g_sessionDone, g_sessionStopped;
static int      g_frameState; // 0 pending, 1 ready, -1 failed
static uint32_t g_failReason;

// ---- registry ----

static void outputName(void* data, struct wl_output* o, const char* name) {
    (void)o;
    struct output* out = data;
    snprintf(out->name, sizeof(out->name), "%s", name);
}
static void outputNoop() {}
static const struct wl_output_listener outputListener = {
    .geometry    = (void*)outputNoop,
    .mode        = (void*)outputNoop,
    .done        = (void*)outputNoop,
    .scale       = (void*)outputNoop,
    .name        = outputName,
    .description = (void*)outputNoop,
};

static void global(void* data, struct wl_registry* reg, uint32_t id, const char* iface, uint32_t version) {
    (void)data;
    if (!strcmp(iface, wl_shm_interface.name))
        g_shm = wl_registry_bind(reg, id, &wl_shm_interface, 1);
    else if (!strcmp(iface, ext_output_image_capture_source_manager_v1_interface.name))
        g_sourceManager = wl_registry_bind(reg, id, &ext_output_image_capture_source_manager_v1_interface, 1);
    else if (!strcmp(iface, ext_image_copy_capture_manager_v1_interface.name))
        g_copyManager = wl_registry_bind(reg, id, &ext_image_copy_capture_manager_v1_interface, 1);
    else if (!strcmp(iface, wl_output_interface.name) && g_outputCount < 16 && version >= 4) {
        struct output* out = &g_outputs[g_outputCount++];
        out->wl            = wl_registry_bind(reg, id, &wl_output_interface, 4);
        wl_output_add_listener(out->wl, &outputListener, out);
    }
}
static void globalRemove(void* d, struct wl_registry* r, uint32_t id) {
    (void)d, (void)r, (void)id;
}
static const struct wl_registry_listener registryListener = {global, globalRemove};

// ---- session ----

static void sBufferSize(void* d, struct ext_image_copy_capture_session_v1* s, uint32_t w, uint32_t h) {
    (void)d, (void)s;
    g_width = w, g_height = h;
}
static void sShmFormat(void* d, struct ext_image_copy_capture_session_v1* s, uint32_t fmt) {
    (void)d, (void)s;
    if (getenv("NANOLEAF_HDR_PROBE_DEBUG"))
        fprintf(stderr, "shm format offered: 0x%08x\n", fmt);
    if (fmt == FMT_XBGR2101010)
        g_hasTenBit = true;
}
static void sDone(void* d, struct ext_image_copy_capture_session_v1* s) {
    (void)d, (void)s;
    g_sessionDone = true;
}
static void sStopped(void* d, struct ext_image_copy_capture_session_v1* s) {
    (void)d, (void)s;
    g_sessionStopped = true;
}
static void sNoop() {}
static const struct ext_image_copy_capture_session_v1_listener sessionListener = {
    .buffer_size    = sBufferSize,
    .shm_format     = sShmFormat,
    .dmabuf_device  = (void*)sNoop,
    .dmabuf_format  = (void*)sNoop,
    .done           = sDone,
    .stopped        = sStopped,
};

// ---- frame ----

static void fReady(void* d, struct ext_image_copy_capture_frame_v1* f) {
    (void)d, (void)f;
    g_frameState = 1;
}
static void fFailed(void* d, struct ext_image_copy_capture_frame_v1* f, uint32_t reason) {
    (void)d, (void)f;
    g_frameState = -1;
    g_failReason = reason;
}
static void fNoop() {}
static const struct ext_image_copy_capture_frame_v1_listener frameListener = {
    .transform         = (void*)fNoop,
    .damage            = (void*)fNoop,
    .presentation_time = (void*)fNoop,
    .ready             = fReady,
    .failed            = fFailed,
};

// ---- analysis ----

// SMPTE ST 2084 EOTF: normalised code -> cd/m².
static double pqToNits(double e) {
    const double m1 = 2610.0 / 16384.0, m2 = 2523.0 / 4096.0 * 128.0;
    const double c1 = 3424.0 / 4096.0, c2 = 2413.0 / 4096.0 * 32.0, c3 = 2392.0 / 4096.0 * 32.0;
    const double p  = pow(e, 1.0 / m2);
    return 10000.0 * pow(fmax(p - c1, 0.0) / (c2 - c3 * p), 1.0 / m1);
}
static double nitsToPq(double nits) {
    const double m1 = 2610.0 / 16384.0, m2 = 2523.0 / 4096.0 * 128.0;
    const double c1 = 3424.0 / 4096.0, c2 = 2413.0 / 4096.0 * 32.0, c3 = 2392.0 / 4096.0 * 32.0;
    const double y = pow(nits / 10000.0, m1);
    return pow((c1 + c2 * y) / (1.0 + c3 * y), m2);
}

static inline void unpack(uint32_t px, unsigned* r, unsigned* g, unsigned* b) {
    *r = px & 0x3ff;
    *g = (px >> 10) & 0x3ff;
    *b = (px >> 20) & 0x3ff;
}

struct patch {
    int x, y, w, h;
};

static void analyse(const uint32_t* px, uint32_t w, uint32_t h, const struct patch* patches, int patchCount) {
    static uint64_t hist[1024];
    memset(hist, 0, sizeof(hist));
    unsigned maxR = 0, maxG = 0, maxB = 0;
    for (uint64_t i = 0; i < (uint64_t)w * h; i++) {
        unsigned r, g, b;
        unpack(px[i], &r, &g, &b);
        if (r > maxR) maxR = r;
        if (g > maxG) maxG = g;
        if (b > maxB) maxB = b;
        unsigned m = r > g ? r : g;
        m          = m > b ? m : b;
        hist[m]++;
    }
    const uint64_t total = (uint64_t)w * h;
    const double   qs[]  = {0.50, 0.90, 0.99, 0.999, 1.0};
    printf("{\"width\":%u,\"height\":%u,\"format\":\"XBGR2101010\",", w, h);
    printf("\"max_code\":{\"r\":%u,\"g\":%u,\"b\":%u},", maxR, maxG, maxB);
    printf("\"max_channel_percentiles\":[");
    for (size_t q = 0; q < sizeof(qs) / sizeof(qs[0]); q++) {
        const uint64_t target = (uint64_t)ceil(qs[q] * (double)total);
        uint64_t       acc    = 0;
        unsigned       code   = 0;
        for (code = 0; code < 1024; code++) {
            acc += hist[code];
            if (acc >= target)
                break;
        }
        if (code > 1023) code = 1023;
        printf("%s{\"q\":%.3f,\"code\":%u,\"pq_nits\":%.1f}", q ? "," : "", qs[q], code, pqToNits(code / 1023.0));
    }
    printf("],");
    // Share of pixels whose brightest channel is above PQ 203 nits (HDR reference white).
    const unsigned whiteCode = (unsigned)lround(nitsToPq(203.0) * 1023.0);
    uint64_t       above     = 0;
    for (unsigned c = whiteCode + 1; c < 1024; c++)
        above += hist[c];
    printf("\"pq_203_code\":%u,\"share_above_203\":%.6f", whiteCode, (double)above / (double)total);

    if (patchCount) {
        printf(",\"patches\":[");
        for (int p = 0; p < patchCount; p++) {
            const struct patch* pt = &patches[p];
            double              sr = 0, sg = 0, sb = 0;
            uint64_t            n  = 0;
            for (int y = pt->y; y < pt->y + pt->h && y < (int)h; y++)
                for (int x = pt->x; x < pt->x + pt->w && x < (int)w; x++) {
                    unsigned r, g, b;
                    unpack(px[(uint64_t)y * w + x], &r, &g, &b);
                    sr += r, sg += g, sb += b, n++;
                }
            if (!n) n = 1;
            printf("%s{\"x\":%d,\"y\":%d,\"w\":%d,\"h\":%d,\"mean_code\":[%.1f,%.1f,%.1f],\"pq_nits\":[%.1f,%.1f,%.1f]}", p ? "," : "", pt->x, pt->y, pt->w,
                   pt->h, sr / n, sg / n, sb / n, pqToNits(sr / n / 1023.0), pqToNits(sg / n / 1023.0), pqToNits(sb / n / 1023.0));
        }
        printf("]");
    }
    printf("}\n");
}

// Dispatch Wayland events, waiting at most `ms`. Returns -1 on timeout or error.
static int dispatchTimeout(struct wl_display* d, int ms) {
    while (wl_display_prepare_read(d) != 0)
        wl_display_dispatch_pending(d);
    wl_display_flush(d);
    struct pollfd p = {.fd = wl_display_get_fd(d), .events = POLLIN};
    if (poll(&p, 1, ms) <= 0) {
        wl_display_cancel_read(d);
        return -1;
    }
    if (wl_display_read_events(d) < 0)
        return -1;
    return wl_display_dispatch_pending(d);
}

#define FRAME_TIMEOUT_MS 3000

// ---- plugin status (hyprctl nanoleafhdr) ----

// Returns malloc'd JSON text, or NULL if the plugin is not loaded.
static char* pluginStatus(void) {
    FILE* f = popen("hyprctl nanoleafhdr 2>/dev/null", "r");
    if (!f)
        return NULL;
    size_t cap = 4096, len = 0;
    char*  buf = malloc(cap);
    size_t n;
    while (buf && (n = fread(buf + len, 1, cap - len - 1, f)) > 0) {
        len += n;
        if (cap - len < 2) {
            cap *= 2;
            buf = realloc(buf, cap);
        }
    }
    pclose(f);
    if (!buf)
        return NULL;
    buf[len] = 0;
    if (!strstr(buf, "\"plugin\":\"nanoleaf-hdr\"")) {
        free(buf);
        return NULL;
    }
    return buf;
}

static long long counter(const char* json, const char* name) {
    char key[64];
    snprintf(key, sizeof(key), "\"%s\":", name);
    const char* p = json ? strstr(json, key) : NULL;
    return p ? atoll(p + strlen(key)) : -1;
}

// Copies the pq_outputs object for `name` into out; false if the output is not listed.
static bool pqOutput(const char* json, const char* name, char* out, size_t outSize) {
    const char* list = json ? strstr(json, "\"pq_outputs\":[") : NULL;
    if (!list)
        return false;
    const char* end = strchr(list, ']');
    char        key[96];
    snprintf(key, sizeof(key), "{\"name\":\"%s\"", name);
    const char* obj = strstr(list, key);
    if (!obj || !end || obj > end)
        return false;
    const char* close = strchr(obj, '}');
    if (!close || (size_t)(close - obj + 2) > outSize)
        return false;
    memcpy(out, obj, (size_t)(close - obj + 1));
    out[close - obj + 1] = 0;
    return true;
}

// Writes data to path atomically (temp file in the same directory, fsync, rename), mode 0600.
static bool writeAtomic(const char* path, const void* data, size_t size) {
    char tmp[4096];
    if (snprintf(tmp, sizeof(tmp), "%s.tmp.%d", path, (int)getpid()) >= (int)sizeof(tmp))
        return false;
    const int fd = open(tmp, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (fd < 0)
        return false;
    const char* p    = data;
    size_t      left = size;
    while (left) {
        const ssize_t w = write(fd, p, left);
        if (w <= 0) {
            close(fd);
            unlink(tmp);
            return false;
        }
        p += w, left -= (size_t)w;
    }
    if (fsync(fd) != 0 || close(fd) != 0 || rename(tmp, path) != 0) {
        unlink(tmp);
        return false;
    }
    return true;
}

// ---- main ----

static int fail(const char* msg) {
    fprintf(stderr, "nanoleaf-hdr-probe: %s\n", msg);
    return 1;
}

int main(int argc, char** argv) {
    const char*  wanted = NULL;
    const char*  rawPath = NULL;
    struct patch patches[MAX_PATCHES];
    int          patchCount = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--output") && i + 1 < argc)
            wanted = argv[++i];
        else if (!strcmp(argv[i], "--raw") && i + 1 < argc)
            rawPath = argv[++i];
        else if (!strcmp(argv[i], "--patch") && i + 1 < argc && patchCount < MAX_PATCHES) {
            struct patch* p = &patches[patchCount];
            if (sscanf(argv[++i], "%d,%d,%d,%d", &p->x, &p->y, &p->w, &p->h) != 4 || p->w <= 0 || p->h <= 0)
                return fail("--patch takes X,Y,W,H in buffer pixels");
            patchCount++;
        } else {
            fprintf(stderr, "usage: %s [--output NAME] [--patch X,Y,W,H]... [--raw FILE]\n", argv[0]);
            return 2;
        }
    }

    struct wl_display* display = wl_display_connect(NULL);
    if (!display)
        return fail("cannot connect to the Wayland display");
    struct wl_registry* registry = wl_display_get_registry(display);
    wl_registry_add_listener(registry, &registryListener, NULL);
    wl_display_roundtrip(display);
    wl_display_roundtrip(display);
    if (!g_shm || !g_sourceManager || !g_copyManager)
        return fail("compositor lacks wl_shm or ext-image-copy-capture-v1");

    struct output* out = NULL;
    for (int i = 0; i < g_outputCount; i++)
        if (!wanted || !strcmp(g_outputs[i].name, wanted)) {
            out = &g_outputs[i];
            break;
        }
    if (!out)
        return fail("output not found");

    // --raw: the plugin must be loaded and list this output as PQ.
    char outputDesc[512] = "";
    if (rawPath) {
        char* status = pluginStatus();
        if (!status) {
            fprintf(stderr, "nanoleaf-hdr-probe: nanoleaf-hdr plugin is not loaded\n");
            return 3;
        }
        const bool pq = pqOutput(status, out->name, outputDesc, sizeof(outputDesc));
        free(status);
        if (!pq) {
            fprintf(stderr, "nanoleaf-hdr-probe: output %s is not a 10-bit PQ output\n", out->name);
            return 3;
        }
    }

    struct ext_image_capture_source_v1* source = ext_output_image_capture_source_manager_v1_create_source(g_sourceManager, out->wl);
    struct ext_image_copy_capture_session_v1* session =
        ext_image_copy_capture_manager_v1_create_session(g_copyManager, source, 0 /* no cursor */);
    ext_image_copy_capture_session_v1_add_listener(session, &sessionListener, NULL);
    while (!g_sessionDone && !g_sessionStopped)
        if (dispatchTimeout(display, FRAME_TIMEOUT_MS) < 0)
            return fail("no capture session offer within 3 s");
    if (g_sessionStopped)
        return fail("capture session stopped (denied or output gone)");
    if (!g_hasTenBit) {
        fprintf(stderr, "nanoleaf-hdr-probe: compositor does not offer XBGR2101010 for this output (is it running 10-bit?)\n");
        return rawPath ? 3 : 1;
    }

    const uint32_t stride = g_width * 4;
    const size_t   size   = (size_t)stride * g_height;
    const int      fd     = memfd_create("nanoleaf-hdr-probe", MFD_CLOEXEC);
    if (fd < 0 || ftruncate(fd, (off_t)size) < 0)
        return fail("cannot allocate the shared buffer");
    uint32_t* pixels = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (pixels == MAP_FAILED)
        return fail("cannot map the shared buffer");
    struct wl_shm_pool* pool   = wl_shm_create_pool(g_shm, fd, (int32_t)size);
    struct wl_buffer*   buffer = wl_shm_pool_create_buffer(pool, 0, (int32_t)g_width, (int32_t)g_height, (int32_t)stride, FMT_XBGR2101010);

    // Capture a few frames and keep the last: the first one may be produced
    // before the compositor's HDR copy for this session exists.
    int frames = 3;
    if (getenv("NANOLEAF_HDR_PROBE_FRAMES"))
        frames = atoi(getenv("NANOLEAF_HDR_PROBE_FRAMES"));
    if (frames < 1)
        frames = 1;
    // With --raw, keep capturing (up to 10 frames) until one is an HDR frame:
    // the plugin's hdr_frames counter rose and converted_frames did not.
    bool lastWasHDR = false;
    if (rawPath && frames < 10)
        frames = 10;
    for (int n = 0; n < frames; n++) {
        char*           before    = rawPath ? pluginStatus() : NULL;
        const long long hdrBefore = counter(before, "hdr_frames"), convBefore = counter(before, "converted_frames");
        free(before);
        g_frameState                                  = 0;
        struct ext_image_copy_capture_frame_v1* frame = ext_image_copy_capture_session_v1_create_frame(session);
        ext_image_copy_capture_frame_v1_add_listener(frame, &frameListener, NULL);
        ext_image_copy_capture_frame_v1_attach_buffer(frame, buffer);
        ext_image_copy_capture_frame_v1_damage_buffer(frame, 0, 0, (int32_t)g_width, (int32_t)g_height);
        ext_image_copy_capture_frame_v1_capture(frame);
        while (g_frameState == 0)
            if (dispatchTimeout(display, FRAME_TIMEOUT_MS) < 0)
                return fail("no frame within 3 s");
        ext_image_copy_capture_frame_v1_destroy(frame);
        if (g_frameState < 0) {
            fprintf(stderr, "nanoleaf-hdr-probe: frame failed (reason %u)\n", g_failReason);
            return 1;
        }
        if (rawPath) {
            char*           after    = pluginStatus();
            const long long hdrAfter = counter(after, "hdr_frames"), convAfter = counter(after, "converted_frames");
            free(after);
            lastWasHDR = hdrBefore >= 0 && hdrAfter > hdrBefore && convAfter == convBefore;
            if (lastWasHDR && n >= 2) // at least the usual warm-up, then the first HDR frame
                break;
        }
    }

    if (rawPath) {
        if (!lastWasHDR) {
            fprintf(stderr, "nanoleaf-hdr-probe: no HDR frame arrived (only Hyprland's SDR conversion)\n");
            return 4;
        }
        char json[1024];
        snprintf(json, sizeof(json),
                 "{\"width\":%u,\"height\":%u,\"stride\":%u,\"format\":\"XBGR2101010\",\"byte_order\":\"little-endian, R in bits 0-9, G 10-19, B 20-29\","
                 "\"range\":\"full\",\"output\":%s,\"converted_frames\":0,\"source\":\"nanoleaf-hdr plugin\"}\n",
                 g_width, g_height, stride, outputDesc);
        if (!writeAtomic(rawPath, pixels, size))
            return fail("cannot write the raw frame");
        char jsonPath[4096];
        snprintf(jsonPath, sizeof(jsonPath), "%s.json", rawPath);
        if (!writeAtomic(jsonPath, json, strlen(json))) {
            unlink(rawPath);
            return fail("cannot write the frame description");
        }
    }

    analyse(pixels, g_width, g_height, patches, patchCount);

    // Drop the pixels from memory (only --raw writes them to disk).
    memset(pixels, 0, size);
    munmap(pixels, size);
    close(fd);
    ext_image_copy_capture_session_v1_destroy(session);
    ext_image_capture_source_v1_destroy(source);
    wl_buffer_destroy(buffer);
    wl_shm_pool_destroy(pool);
    wl_display_disconnect(display);
    return 0;
}
