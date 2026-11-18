// nanoleaf-hdr-ladder: a test window that shows grey patches at known HDR
// luminances, tagged as SMPTE ST 2084 (PQ) / BT.2020 through
// wp-color-management-v1. Used as ground truth for the plugin test.
//
//   nanoleaf-hdr-ladder [NITS...]     (default: 100 203 465 1000)
//
// The window is split into equal vertical bands, one per value, left to right.

#define _GNU_SOURCE
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#include <wayland-client.h>

#include "color-management-v1-client-protocol.h"
#include "xdg-shell-client-protocol.h"

#define FMT_XBGR2101010 0x30334258u
#define MAX_BANDS 16

static struct wl_compositor*      g_compositor;
static struct wl_shm*             g_shm;
static struct xdg_wm_base*        g_wm;
static struct wp_color_manager_v1* g_cm;
static bool                       g_pqSupported, g_bt2020Supported, g_parametric, g_cmDone;
static int                        g_descState; // 0 pending, 1 ready, -1 failed
static int                        g_width = 1280, g_height = 720;
static bool                       g_configured;
static double                     g_nits[MAX_BANDS];
static int                        g_bands;

static double nitsToPq(double nits) {
    const double m1 = 2610.0 / 16384.0, m2 = 2523.0 / 4096.0 * 128.0;
    const double c1 = 3424.0 / 4096.0, c2 = 2413.0 / 4096.0 * 32.0, c3 = 2392.0 / 4096.0 * 32.0;
    const double y = pow(nits / 10000.0, m1);
    return pow((c1 + c2 * y) / (1.0 + c3 * y), m2);
}

static void noop() {}

// colour manager capabilities
static void cmFeature(void* d, struct wp_color_manager_v1* m, uint32_t f) {
    (void)d, (void)m;
    if (f == WP_COLOR_MANAGER_V1_FEATURE_PARAMETRIC)
        g_parametric = true;
}
static void cmTf(void* d, struct wp_color_manager_v1* m, uint32_t tf) {
    (void)d, (void)m;
    if (tf == WP_COLOR_MANAGER_V1_TRANSFER_FUNCTION_ST2084_PQ)
        g_pqSupported = true;
}
static void cmPrimaries(void* d, struct wp_color_manager_v1* m, uint32_t p) {
    (void)d, (void)m;
    if (p == WP_COLOR_MANAGER_V1_PRIMARIES_BT2020)
        g_bt2020Supported = true;
}
static void cmDone(void* d, struct wp_color_manager_v1* m) {
    (void)d, (void)m;
    g_cmDone = true;
}
static const struct wp_color_manager_v1_listener cmListener = {
    .supported_intent          = (void*)noop,
    .supported_feature         = cmFeature,
    .supported_tf_named        = cmTf,
    .supported_primaries_named = cmPrimaries,
    .done                      = cmDone,
};

static void descFailed(void* d, struct wp_image_description_v1* i, uint32_t cause, const char* msg) {
    (void)d, (void)i;
    fprintf(stderr, "nanoleaf-hdr-ladder: image description failed (%u): %s\n", cause, msg);
    g_descState = -1;
}
static void descReady(void* d, struct wp_image_description_v1* i, uint32_t id) {
    (void)d, (void)i, (void)id;
    g_descState = 1;
}
static void descReady2(void* d, struct wp_image_description_v1* i, uint32_t hi, uint32_t lo) {
    (void)d, (void)i, (void)hi, (void)lo;
    g_descState = 1;
}
static const struct wp_image_description_v1_listener descListener = {
    .failed = descFailed,
    .ready  = descReady,
    .ready2 = descReady2,
};

static void wmPing(void* d, struct xdg_wm_base* wm, uint32_t serial) {
    (void)d;
    xdg_wm_base_pong(wm, serial);
}
static const struct xdg_wm_base_listener wmListener = {.ping = wmPing};

static void global(void* d, struct wl_registry* reg, uint32_t id, const char* iface, uint32_t version) {
    (void)d;
    if (!strcmp(iface, wl_compositor_interface.name))
        g_compositor = wl_registry_bind(reg, id, &wl_compositor_interface, 4);
    else if (!strcmp(iface, wl_shm_interface.name))
        g_shm = wl_registry_bind(reg, id, &wl_shm_interface, 1);
    else if (!strcmp(iface, xdg_wm_base_interface.name)) {
        g_wm = wl_registry_bind(reg, id, &xdg_wm_base_interface, 1);
        xdg_wm_base_add_listener(g_wm, &wmListener, NULL);
    } else if (!strcmp(iface, wp_color_manager_v1_interface.name)) {
        g_cm = wl_registry_bind(reg, id, &wp_color_manager_v1_interface, version < 2 ? version : 2);
        wp_color_manager_v1_add_listener(g_cm, &cmListener, NULL);
    }
}
static void globalRemove(void* d, struct wl_registry* r, uint32_t id) {
    (void)d, (void)r, (void)id;
}
static const struct wl_registry_listener registryListener = {global, globalRemove};

static void xdgSurfaceConfigure(void* d, struct xdg_surface* s, uint32_t serial) {
    (void)d;
    xdg_surface_ack_configure(s, serial);
    g_configured = true;
}
static const struct xdg_surface_listener xdgSurfaceListener = {.configure = xdgSurfaceConfigure};

static void toplevelConfigure(void* d, struct xdg_toplevel* t, int32_t w, int32_t h, struct wl_array* states) {
    (void)d, (void)t, (void)states;
    if (w > 0 && h > 0)
        g_width = w, g_height = h;
}
static void toplevelClose(void* d, struct xdg_toplevel* t) {
    (void)d, (void)t;
    exit(0);
}
static const struct xdg_toplevel_listener toplevelListener = {
    .configure        = toplevelConfigure,
    .close            = toplevelClose,
    .configure_bounds = (void*)noop,
    .wm_capabilities  = (void*)noop,
};

static struct wl_buffer* makeBuffer(void) {
    const int    stride = g_width * 4;
    const size_t size   = (size_t)stride * g_height;
    const int    fd     = memfd_create("nanoleaf-hdr-ladder", MFD_CLOEXEC);
    if (fd < 0 || ftruncate(fd, (off_t)size) < 0)
        return NULL;
    uint32_t* px = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (px == MAP_FAILED)
        return NULL;
    for (int x = 0; x < g_width; x++) {
        const double   nits = g_nits[x * g_bands / g_width];
        const uint32_t c    = (uint32_t)lround(nitsToPq(nits) * 1023.0);
        const uint32_t v    = c | (c << 10) | (c << 20) | (3u << 30);
        for (int y = 0; y < g_height; y++)
            px[(size_t)y * g_width + x] = v;
    }
    munmap(px, size);
    struct wl_shm_pool* pool = wl_shm_create_pool(g_shm, fd, (int32_t)size);
    struct wl_buffer*   buf  = wl_shm_pool_create_buffer(pool, 0, g_width, g_height, stride, FMT_XBGR2101010);
    wl_shm_pool_destroy(pool);
    close(fd);
    return buf;
}

int main(int argc, char** argv) {
    for (int i = 1; i < argc && g_bands < MAX_BANDS; i++)
        g_nits[g_bands++] = atof(argv[i]);
    if (!g_bands) {
        const double def[] = {100, 203, 465, 1000};
        for (int i = 0; i < 4; i++)
            g_nits[g_bands++] = def[i];
    }

    struct wl_display* display = wl_display_connect(NULL);
    if (!display)
        return fprintf(stderr, "nanoleaf-hdr-ladder: no Wayland display\n"), 1;
    wl_registry_add_listener(wl_display_get_registry(display), &registryListener, NULL);
    wl_display_roundtrip(display);
    wl_display_roundtrip(display);
    if (!g_compositor || !g_shm || !g_wm || !g_cm)
        return fprintf(stderr, "nanoleaf-hdr-ladder: compositor lacks a required protocol (color-management-v1?)\n"), 1;
    if (!g_parametric || !g_pqSupported || !g_bt2020Supported)
        return fprintf(stderr, "nanoleaf-hdr-ladder: compositor does not accept parametric PQ/BT.2020 descriptions\n"), 1;

    struct wl_surface*                  surface = wl_compositor_create_surface(g_compositor);
    struct wp_color_management_surface_v1* cms  = wp_color_manager_v1_get_surface(g_cm, surface);
    struct wp_image_description_creator_params_v1* creator = wp_color_manager_v1_create_parametric_creator(g_cm);
    wp_image_description_creator_params_v1_set_tf_named(creator, WP_COLOR_MANAGER_V1_TRANSFER_FUNCTION_ST2084_PQ);
    wp_image_description_creator_params_v1_set_primaries_named(creator, WP_COLOR_MANAGER_V1_PRIMARIES_BT2020);
    struct wp_image_description_v1* desc = wp_image_description_creator_params_v1_create(creator);
    wp_image_description_v1_add_listener(desc, &descListener, NULL);
    while (g_descState == 0 && wl_display_dispatch(display) != -1) {}
    if (g_descState < 0)
        return 1;
    wp_color_management_surface_v1_set_image_description(cms, desc, WP_COLOR_MANAGER_V1_RENDER_INTENT_PERCEPTUAL);

    struct xdg_surface*  xs = xdg_wm_base_get_xdg_surface(g_wm, surface);
    struct xdg_toplevel* tl = xdg_surface_get_toplevel(xs);
    xdg_surface_add_listener(xs, &xdgSurfaceListener, NULL);
    xdg_toplevel_add_listener(tl, &toplevelListener, NULL);
    xdg_toplevel_set_title(tl, "nanoleaf-hdr-ladder");
    xdg_toplevel_set_app_id(tl, "nanoleaf-hdr-ladder");
    wl_surface_commit(surface);
    while (!g_configured && wl_display_dispatch(display) != -1) {}

    int lastW = 0, lastH = 0;
    for (;;) {
        if (g_width != lastW || g_height != lastH) {
            struct wl_buffer* buf = makeBuffer();
            if (!buf)
                return fprintf(stderr, "nanoleaf-hdr-ladder: buffer allocation failed\n"), 1;
            wl_surface_attach(surface, buf, 0, 0);
            wl_surface_damage_buffer(surface, 0, 0, g_width, g_height);
            wl_surface_commit(surface);
            lastW = g_width, lastH = g_height;
            printf("showing %dx%d:", g_width, g_height);
            for (int i = 0; i < g_bands; i++)
                printf(" %.0f nits (code %ld)", g_nits[i], lround(nitsToPq(g_nits[i]) * 1023.0));
            printf("\n");
            fflush(stdout);
        }
        if (wl_display_dispatch(display) == -1)
            break;
    }
    return 0;
}
