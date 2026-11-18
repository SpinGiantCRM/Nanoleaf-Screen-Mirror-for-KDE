// nanoleaf-hdr: let one opted-in screen-capture client receive the monitor's
// real HDR (PQ) picture from Hyprland 0.57.2 instead of the SDR sRGB copy.
//
// What it changes, and only while an opted-in client is capturing a PQ
// monitor into a 10-bit buffer:
//   1. After Hyprland saves its normal (SDR) mirror copy, the plugin also
//      copies the composited work buffer into its own 10-bit framebuffer,
//      tagged with the monitor's own image description (PQ).
//   2. For that client's frames, the capture target is tagged with the same
//      description and the plugin's framebuffer is used as the source, so the
//      copy is a straight PQ -> PQ copy of what the monitor shows.
// Every other capture client, and Hyprland's own mirror, are untouched.
// Permissions, noscreenshare redaction and the protocol flow stay Hyprland's.
//
// See ../README.md. Built for Hyprland 0.57.2 only; refuses other builds.

#include <cstdint>
#include <filesystem>
#include <format>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <chrono>
#include <sstream>

#include <drm_fourcc.h>
#include <wayland-server-core.h>

// Standard headers first: the access override below must not reach them.
#include <algorithm>
#include <any>
#include <array>
#include <deque>
#include <functional>
#include <list>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <ranges>
#include <set>
#include <span>
#include <thread>
#include <variant>
#include <vector>
#include <hyprlang.hpp>

#define private public
#define protected public
#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/Compositor.hpp>
#include <hyprland/src/state/MonitorState.hpp>
#include <hyprland/src/output/Monitor.hpp>
#include <hyprland/src/output/MonitorResources.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/render/OpenGL.hpp>
#include <hyprland/src/render/Framebuffer.hpp>
#include <hyprland/src/managers/screenshare/ScreenshareManager.hpp>
#include <hyprland/src/protocols/types/Buffer.hpp>
#include <hyprland/src/config/values/types/BoolValue.hpp>
#include <hyprland/src/config/values/types/StringValue.hpp>
#undef private
#undef protected

using namespace NColorManagement;
using Clock = std::chrono::steady_clock;

static HANDLE PHANDLE = nullptr;

// Hyprland release this was written and checked against.
static constexpr const char* SUPPORTED_TAG = "v0.57.2";
// Stop the extra copy when no opted-in frame was requested for this long.
static constexpr auto IDLE_DISARM = std::chrono::seconds(2);

static struct {
    SP<Config::Values::CBoolValue>   enabled;
    SP<Config::Values::CStringValue> clients;
} g_config;

static CFunctionHook* g_saveMirrorHook    = nullptr;
static CFunctionHook* g_renderMonitorHook = nullptr;
static CFunctionHook* g_beginCopyHook     = nullptr;
static CFunctionHook* g_constraintsHook   = nullptr;

static SP<IPC::Socket1::SCommand> g_statusCommand;

struct SMonitorState {
    SP<Render::IFramebuffer> fb;
    bool                     valid       = false; // fb holds a complete current frame
    Clock::time_point        lastRequest = {};
    uint64_t                 copies      = 0;
};

// Keyed by monitor name: monitors can be recreated, names are stable.
static std::unordered_map<std::string, SMonitorState> g_monitors;

static struct {
    uint64_t saveMirror     = 0;
    uint64_t renderMonitor  = 0;
    uint64_t beginCopy      = 0;
    uint64_t formatOffers   = 0; // sessions offered XBGR2101010
    uint64_t hdrFrames      = 0; // frames delivered from the HDR framebuffer
    uint64_t convertedFrames = 0; // opted-in frames converted from the SDR mirror (HDR copy not ready)
} g_counters;

static std::unordered_map<pid_t, bool> g_pidAllowed;

static bool isTenBit(uint32_t fmt) {
    return fmt == DRM_FORMAT_XBGR2101010 || fmt == DRM_FORMAT_ABGR2101010 || fmt == DRM_FORMAT_XRGB2101010 || fmt == DRM_FORMAT_ARGB2101010;
}

static bool monitorIsPQ(const PHLMONITOR& mon) {
    return mon && mon->m_enabled10bit && mon->m_imageDescription && mon->m_imageDescription->value().transferFunction == CM_TRANSFER_FUNCTION_ST2084_PQ;
}

static std::unordered_set<std::string> allowedNames() {
    std::unordered_set<std::string> names;
    std::stringstream               ss(g_config.clients ? std::string(g_config.clients->value()) : std::string());
    std::string                     item;
    while (std::getline(ss, item, ',')) {
        const auto b = item.find_first_not_of(" \t");
        const auto e = item.find_last_not_of(" \t");
        if (b != std::string::npos)
            names.insert(item.substr(b, e - b + 1));
    }
    return names;
}

static bool clientAllowed(wl_client* client) {
    if (!client)
        return false;
    pid_t pid = 0;
    uid_t uid = 0;
    gid_t gid = 0;
    wl_client_get_credentials(client, &pid, &uid, &gid);
    if (pid <= 0 || uid != getuid())
        return false;

    if (const auto it = g_pidAllowed.find(pid); it != g_pidAllowed.end())
        return it->second;

    std::error_code ec;
    const auto      exe     = std::filesystem::read_symlink(std::format("/proc/{}/exe", pid), ec);
    const bool      allowed = !ec && allowedNames().contains(exe.filename().string());
    g_pidAllowed[pid]       = allowed;
    return allowed;
}

static uint32_t bufferFormat(Screenshare::CScreenshareFrame* frame) {
    if (!frame->m_buffer)
        return 0;
    if (const auto shm = frame->m_buffer->shm(); shm.success)
        return shm.format;
    if (const auto dma = frame->m_buffer->dmabuf(); dma.success)
        return dma.format;
    return 0;
}

// True when this frame should get the monitor's PQ picture.
static bool frameWantsHDR(Screenshare::CScreenshareFrame* frame) {
    if (!g_config.enabled || !g_config.enabled->value())
        return false;
    // Sessions are owned by unique pointers: use the weak pointer directly, never lock() it.
    const auto& session = frame->m_session;
    if (!session || session.expired())
        return false;
    if (session->m_type != Screenshare::SHARE_MONITOR && session->m_type != Screenshare::SHARE_REGION)
        return false;
    if (!monitorIsPQ(session->monitor()))
        return false;
    if (!isTenBit(bufferFormat(frame)))
        return false;
    return clientAllowed(session->m_client);
}

// ---- hook 0: offer a 10-bit format to opted-in clients only ----
// misc:screencopy_force_8b (default on) limits every client to 8-bit. The
// opted-in client gets XBGR2101010 added; every other client's list is unchanged.

typedef void (*origConstraints)(Screenshare::CScreenshareSession*);

static void hkCalculateConstraints(Screenshare::CScreenshareSession* thisptr) {
    (*(origConstraints)g_constraintsHook->m_original)(thisptr);

    if (!g_config.enabled || !g_config.enabled->value())
        return;
    if (thisptr->m_type != Screenshare::SHARE_MONITOR && thisptr->m_type != Screenshare::SHARE_REGION)
        return;
    if (!monitorIsPQ(thisptr->monitor()) || !clientAllowed(thisptr->m_client))
        return;
    if (std::ranges::find(thisptr->m_formats, DRM_FORMAT_XBGR2101010) != thisptr->m_formats.end())
        return;
    thisptr->m_formats.push_back(DRM_FORMAT_XBGR2101010);
    g_counters.formatOffers++;
    // Arm the HDR copy now so the client's first frame can already use it.
    g_monitors[thisptr->monitor()->m_name].lastRequest = Clock::now();
}

// ---- hook 1: after Hyprland saves its mirror copy, refresh the HDR copy ----

typedef bool (*origSaveMirror)(Render::GL::CHyprOpenGLImpl*, Render::CRenderContext&, const CBox&);

static bool hkSaveBufferForMirror(Render::GL::CHyprOpenGLImpl* thisptr, Render::CRenderContext& ctx, const CBox& box) {
    g_counters.saveMirror++;
    const bool result = (*(origSaveMirror)g_saveMirrorHook->m_original)(thisptr, ctx, box);

    const auto mon = ctx.m_data.pMonitor.lock();
    if (!mon)
        return result;

    const auto it = g_monitors.find(mon->m_name);
    if (it == g_monitors.end())
        return result;
    auto& st = it->second;

    // Disarm when idle, disabled, or the monitor left PQ.
    if (Clock::now() - st.lastRequest > IDLE_DISARM || !g_config.enabled->value() || !monitorIsPQ(mon)) {
        if (st.fb)
            st.fb->release();
        g_monitors.erase(it);
        g_pidAllowed.clear();
        return result;
    }

    const auto workFB = ctx.m_data.currentFB;
    const auto TEX    = workFB ? workFB->getTexture() : nullptr;
    if (!TEX || !TEX->m_imageDescription)
        return result;

    const auto SIZE = mon->resources()->m_size;
    if (!st.fb)
        st.fb = g_pHyprRenderer->createFB(std::format("nanoleaf-hdr {}", mon->m_name));
    if (!st.fb->isAllocated() || st.fb->m_size != SIZE) {
        st.fb->release();
        if (!st.fb->alloc(SIZE.x, SIZE.y, DRM_FORMAT_XRGB2101010)) {
            st.valid = false;
            return result;
        }
        st.valid = false;
    }
    // Re-tag every frame: the monitor's description can change (luminances, HDR toggle).
    st.fb->setImageDescription(mon->m_imageDescription);

    // First frame after (re)allocation copies everything; later ones only the damage.
    CRegion        fullDamage{0, 0, SIZE.x, SIZE.y};
    const CRegion* damage = st.valid ? &ctx.m_data.finalDamage : &fullDamage;

    {
        auto guard = g_pHyprRenderer->bindTempFB(ctx, st.fb);
        thisptr->blend(false);
        thisptr->renderTexture(ctx, TEX, box,
                               Render::GL::CHyprOpenGLImpl::STextureRenderData{
                                   .damage        = damage,
                                   .a             = 1.F,
                                   .round         = 0,
                                   .discardActive = false,
                                   .allowCustomUV = false,
                               });
        thisptr->blend(true);
    }

    st.valid = true;
    st.copies++;
    return result;
}

// ---- hook 2: tag the opted-in client's capture target as the monitor's PQ ----

typedef bool (*origBeginCopy)(Screenshare::CScreenshareFrame*, SP<Render::IFramebuffer>);

static bool hkBeginCopy(Screenshare::CScreenshareFrame* thisptr, SP<Render::IFramebuffer> framebuffer) {
    g_counters.beginCopy++;
    const bool ok = (*(origBeginCopy)g_beginCopyHook->m_original)(thisptr, framebuffer);
    if (!ok || !frameWantsHDR(thisptr))
        return ok;

    const auto mon = thisptr->m_session->monitor();
    auto&      ctx = g_pHyprRenderer->context();
    if (ctx.m_data.outFB)
        ctx.m_data.outFB->setImageDescription(mon->m_imageDescription);

    // Arm the per-frame HDR copy for this monitor.
    auto& st       = g_monitors[mon->m_name];
    st.lastRequest = Clock::now();
    return ok;
}

// ---- hook 3: give the opted-in client the HDR framebuffer as the source ----

typedef void (*origRenderMonitor)(Screenshare::CScreenshareFrame*, Render::CRenderContext&);

static void hkRenderMonitor(Screenshare::CScreenshareFrame* thisptr, Render::CRenderContext& ctx) {
    g_counters.renderMonitor++;
    const auto orig = (origRenderMonitor)g_renderMonitorHook->m_original;

    // Only for the opted-in client, and only if beginCopy tagged this target.
    if (!frameWantsHDR(thisptr) || !ctx.m_data.outFB || !ctx.m_data.outFB->imageDescription() ||
        ctx.m_data.outFB->imageDescription()->value().transferFunction != CM_TRANSFER_FUNCTION_ST2084_PQ) {
        (*orig)(thisptr, ctx);
        return;
    }

    const auto mon = thisptr->m_session->monitor();
    const auto it  = g_monitors.find(mon->m_name);
    // resources() is a weak pointer over a unique pointer: dereference, never lock() it.
    const auto res = mon->resources();

    if (it == g_monitors.end() || !it->second.valid || !it->second.fb || !res || res.expired()) {
        // HDR copy not ready yet: Hyprland converts its SDR mirror into the PQ
        // target. Correctly encoded, just without highlights above SDR white.
        g_counters.convertedFrames++;
        (*orig)(thisptr, ctx);
        return;
    }

    // Swap our framebuffer in as the monitor's mirror for this one draw, so
    // Hyprland's own code (region crop, noscreenshare redaction) runs unchanged.
    std::swap(res->m_monitorMirrorFB, it->second.fb);
    (*orig)(thisptr, ctx);
    std::swap(res->m_monitorMirrorFB, it->second.fb);
    g_counters.hdrFrames++;
}

// ---- hyprctl nanoleafhdr: what the plugin delivers, for clients to check ----

static std::string escapeJSON(const std::string& s) {
    std::string out;
    for (const char c : s) {
        if (c == '"' || c == '\\')
            out += '\\';
        out += c;
    }
    return out;
}

static IPC::Socket1::SResponse statusCommand(const IPC::Socket1::SRequest&) {
    std::string monitors;
    for (const auto& [name, st] : g_monitors) {
        if (!monitors.empty())
            monitors += ",";
        monitors += std::format(R"({{"name":"{}","valid":{},"copies":{}}})", escapeJSON(name), st.valid ? "true" : "false", st.copies);
    }

    // Describe every PQ monitor so a client can check the encoding it will get.
    std::string outputs;
    std::string all;
    for (auto const& mon : State::monitorState()->monitors()) {
        if (!all.empty())
            all += ",";
        all += std::format(R"({{"name":"{}","ten_bit":{},"transfer":{},"pq":{}}})", escapeJSON(mon->m_name), mon->m_enabled10bit ? "true" : "false",
                           mon->m_imageDescription ? (int)mon->m_imageDescription->value().transferFunction : -1, monitorIsPQ(mon) ? "true" : "false");
        if (!monitorIsPQ(mon))
            continue;
        const auto& v = mon->m_imageDescription->value();
        if (!outputs.empty())
            outputs += ",";
        outputs += std::format(R"({{"name":"{}","transfer":"st2084_pq","primaries":"{}","min_nits":{},"max_nits":{},"reference_nits":{},"format":"XBGR2101010"}})",
                               escapeJSON(mon->m_name), v.primariesNamed == CM_PRIMARIES_BT2020 ? "bt2020" : "other", v.luminances.min, v.luminances.max,
                               v.luminances.reference);
    }

    return IPC::Socket1::SResponse(std::format(
        R"({{"plugin":"nanoleaf-hdr","version":"0.1.0","hyprland":"{}","enabled":{},"clients":"{}","outputs":[{}],"pq_outputs":[{}],"armed":[{}],"counters":{{"format_offers":{},"save_mirror":{},"begin_copy":{},"render_monitor":{},"hdr_frames":{},"converted_frames":{}}}}})",
        SUPPORTED_TAG, g_config.enabled->value() ? "true" : "false", escapeJSON(std::string(g_config.clients->value())), all, outputs, monitors, g_counters.formatOffers, g_counters.saveMirror,
        g_counters.beginCopy, g_counters.renderMonitor, g_counters.hdrFrames, g_counters.convertedFrames));
}

// ---- plugin entry points ----

APICALL EXPORT std::string PLUGIN_API_VERSION() {
    return HYPRLAND_API_VERSION;
}

static void fail(const std::string& why) {
    HyprlandAPI::addNotification(PHANDLE, "[nanoleaf-hdr] " + why, CHyprColor{1.0, 0.2, 0.2, 1.0}, 8000);
    throw std::runtime_error("[nanoleaf-hdr] " + why);
}

static void* findOne(const std::string& name, const std::string& owner) {
    for (const auto& fn : HyprlandAPI::findFunctionsByName(PHANDLE, name)) {
        if (fn.demangled.contains(owner))
            return fn.address;
    }
    return nullptr;
}

APICALL EXPORT PLUGIN_DESCRIPTION_INFO PLUGIN_INIT(HANDLE handle) {
    PHANDLE = handle;

    if (std::string(__hyprland_api_get_hash()) != std::string(__hyprland_api_get_client_hash()))
        fail("built against different Hyprland headers than the running Hyprland; rebuild the plugin");

    const auto version = HyprlandAPI::getHyprlandVersion(PHANDLE);
    if (version.tag != SUPPORTED_TAG)
        fail(std::format("written for Hyprland {} only, running {}; not loading", SUPPORTED_TAG, version.tag));

    g_config.enabled = makeShared<Config::Values::CBoolValue>("plugin:nanoleaf_hdr:enabled", "Give opted-in capture clients the monitor's HDR (PQ) picture", true);
    g_config.clients = makeShared<Config::Values::CStringValue>("plugin:nanoleaf_hdr:clients",
                                                                "Comma-separated executable names allowed to receive HDR capture", "nanoleaf-hdr-probe");
    HyprlandAPI::addConfigValueV2(PHANDLE, g_config.enabled);
    HyprlandAPI::addConfigValueV2(PHANDLE, g_config.clients);

    const auto saveMirror    = findOne("saveBufferForMirror", "CHyprOpenGLImpl::saveBufferForMirror(Render::CRenderContext&");
    const auto renderMonitor = findOne("renderMonitor", "CScreenshareFrame::renderMonitor(Render::CRenderContext&)");
    const auto beginCopy     = findOne("beginCopy", "CScreenshareFrame::beginCopy(");
    const auto constraints   = findOne("calculateConstraints", "CScreenshareSession::calculateConstraints()");
    if (!saveMirror || !renderMonitor || !beginCopy || !constraints)
        fail("a function this plugin hooks was not found in this Hyprland build");

    g_saveMirrorHook    = HyprlandAPI::createFunctionHook(PHANDLE, saveMirror, (void*)::hkSaveBufferForMirror);
    g_renderMonitorHook = HyprlandAPI::createFunctionHook(PHANDLE, renderMonitor, (void*)::hkRenderMonitor);
    g_beginCopyHook     = HyprlandAPI::createFunctionHook(PHANDLE, beginCopy, (void*)::hkBeginCopy);
    g_constraintsHook   = HyprlandAPI::createFunctionHook(PHANDLE, constraints, (void*)::hkCalculateConstraints);
    if (!g_saveMirrorHook || !g_renderMonitorHook || !g_beginCopyHook || !g_constraintsHook)
        fail("could not create function hooks");

    if (!g_saveMirrorHook->hook() || !g_beginCopyHook->hook() || !g_renderMonitorHook->hook() || !g_constraintsHook->hook()) {
        for (auto* hook : {g_saveMirrorHook, g_beginCopyHook, g_renderMonitorHook, g_constraintsHook})
            hook->unhook();
        fail("hooking failed; nothing was changed");
    }

    g_statusCommand = HyprlandAPI::registerHyprCtlCommand(PHANDLE, IPC::Socket1::SCommand{.name = "nanoleafhdr", .handler = statusCommand});

    HyprlandAPI::addNotification(PHANDLE, "[nanoleaf-hdr] loaded", CHyprColor{0.2, 1.0, 0.2, 1.0}, 3000);
    return {"nanoleaf-hdr", "HDR (PQ) screen capture for opted-in clients", "Nanoleaf Screen Mirror", "0.1.0"};
}

APICALL EXPORT void PLUGIN_EXIT() {
    // Hyprland removes hooks and the hyprctl command for this handle. Free our framebuffers.
    for (auto& [name, st] : g_monitors) {
        if (st.fb)
            st.fb->release();
    }
    g_monitors.clear();
    g_pidAllowed.clear();
    g_config = {};
}
