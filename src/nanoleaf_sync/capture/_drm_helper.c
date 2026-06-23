/*
 * Nanoleaf DRM framebuffer helper.
 *
 * Two approaches:
 *   1. Fresh open + CAP_SYS_ADMIN + UNIVERSAL_PLANES → GETPLANE (AMD/Intel)
 *   2. Clone KWin's master fd via pidfd_getfd → GETFB/GETFB2 (NVIDIA)
 *
 * Protocol: connects to Unix socket, sends 44-byte struct {offset, size, pitch,
 * fourcc, fb_id, width, height, modifier_lo, modifier_hi} followed by
 * SCM_RIGHTS passing the DMA-BUF fd (or GEM mmap fd).
 */

#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <sys/un.h>
#include <unistd.h>

/* ------------------------------------------------------------------ */
/* DRM ioctl constants and structs  (avoiding libdrm dep)             */
/* ------------------------------------------------------------------ */

#define _IOC_NRBITS 8
#define _IOC_TYPEBITS 8
#define _IOC_SIZEBITS 14
#define _IOC_DIRBITS 2
#define _IOC_NRSHIFT 0
#define _IOC_TYPESHIFT (_IOC_NRSHIFT + _IOC_NRBITS)
#define _IOC_SIZESHIFT (_IOC_TYPESHIFT + _IOC_TYPEBITS)
#define _IOC_DIRSHIFT (_IOC_SIZESHIFT + _IOC_SIZEBITS)
#define _IOC_NONE 0U
#define _IOC_WRITE 1U
#define _IOC_READ 2U
#define _IOC(dir, type, nr, size) \
    (((dir) << _IOC_DIRSHIFT) | ((type) << _IOC_TYPESHIFT) | ((nr) << _IOC_NRSHIFT) | \
     ((size) << _IOC_SIZESHIFT))

#define DRM_IOCTL_BASE 'd'
#define DRM_IOWR(nr, type) _IOC(_IOC_READ | _IOC_WRITE, DRM_IOCTL_BASE, nr, sizeof(type))

/* --- structs --- */

struct drm_mode_fb_cmd {
    uint32_t fb_id;
    uint32_t width;
    uint32_t height;
    uint32_t pitch;
    uint32_t bpp;
    uint32_t depth;
    uint32_t handle;
};

struct drm_mode_fb_cmd2 {
    uint32_t fb_id;
    uint32_t width;
    uint32_t height;
    uint32_t pixel_format;
    uint32_t flags;
    uint32_t handles[4];
    uint32_t pitches[4];
    uint32_t offsets[4];
    uint32_t _pad4;             /* padding for 8-byte alignment of modifier */
    uint64_t modifier[4];
};

struct drm_mode_crtc {
    uint64_t set_connectors_ptr;
    uint32_t count_connectors;
    uint32_t crtc_id;
    uint32_t fb_id;
    uint32_t gamma_size;
    uint16_t mode_valid;
    uint16_t pad;
    struct { /* drm_mode_modeinfo — 68 bytes */
        uint32_t clock;
        uint16_t hdisplay, hsync_start, hsync_end, htotal, hskew;
        uint16_t vdisplay, vsync_start, vsync_end, vtotal, vscan;
        uint32_t vrefresh, flags, type;
        char name[32];
    } mode;
};

struct drm_set_client_cap {
    uint64_t capability;
    uint64_t value;
};

struct drm_mode_get_plane_res {
    uint64_t plane_id_ptr;
    uint32_t count_planes;
    uint32_t pad;
};

struct drm_mode_get_plane {
    uint32_t plane_id;
    uint32_t crtc_id;
    uint32_t fb_id;
    uint32_t possible_crtcs;
    uint32_t gamma_size;
    uint32_t count_format_types;
    uint64_t format_type_ptr;
};

struct drm_mode_map_dumb {
    uint32_t handle;
    uint32_t pad;
    uint64_t offset;
};

struct drm_prime_handle {
    uint32_t handle;
    uint32_t flags;
    int32_t fd;
};

struct drm_gem_flink {
    uint32_t handle;
    uint32_t name;
};

struct drm_gem_open {
    uint32_t name;
    uint32_t handle;
    uint64_t size;
};

/* --- ioctl numbers --- */

#define DRM_IOCTL_MODE_GETRESOURCES DRM_IOWR(0xA0, struct drm_mode_card_res)
#define DRM_IOCTL_MODE_GETCRTC DRM_IOWR(0xA1, struct drm_mode_crtc)
#define DRM_IOCTL_SET_CLIENT_CAP DRM_IOWR(0x0D, struct drm_set_client_cap)
#define DRM_IOCTL_MODE_GETPLANERESOURCES DRM_IOWR(0xB5, struct drm_mode_get_plane_res)
#define DRM_IOCTL_MODE_GETPLANE DRM_IOWR(0xB6, struct drm_mode_get_plane)
#define DRM_IOCTL_MODE_GETFB DRM_IOWR(0xAD, struct drm_mode_fb_cmd)
#define DRM_IOCTL_MODE_GETFB2 DRM_IOWR(0xCE, struct drm_mode_fb_cmd2)
#define DRM_IOCTL_MODE_MAP_DUMB DRM_IOWR(0xB3, struct drm_mode_map_dumb)
#define DRM_IOCTL_PRIME_HANDLE_TO_FD DRM_IOWR(0x2D, struct drm_prime_handle)
#define DRM_IOCTL_GEM_FLINK DRM_IOWR(0xB9, struct drm_gem_flink)
#define DRM_IOCTL_GEM_OPEN DRM_IOWR(0xB7, struct drm_gem_open)
#define DRM_IOCTL_MODE_GETCONNECTOR DRM_IOWR(0xA7, struct drm_mode_get_connector)

#define DRM_CLIENT_CAP_UNIVERSAL_PLANES 2
#define DRM_CLOEXEC 0x01
#define DRM_MODE_CONNECTED 1

/* card resources for CRTC enumeration */
struct drm_mode_card_res {
    uint64_t fb_id_ptr;
    uint64_t crtc_id_ptr;
    uint64_t connector_id_ptr;
    uint64_t encoder_id_ptr;
    uint32_t count_fbs;
    uint32_t count_crtcs;
    uint32_t count_connectors;
    uint32_t count_encoders;
    uint32_t min_width, max_width, min_height, max_height;
};

struct drm_mode_get_connector {
    uint32_t connector_id;
    uint32_t encoder_id;
    uint32_t crtc_id;
    uint32_t connector_type;
    uint32_t connector_type_id;
    uint32_t connection;
    uint32_t mm_width, mm_height;
    uint32_t subpixel;
    uint32_t count_modes;
    uint32_t count_props;
    uint32_t count_encoders;
    uint64_t modes_ptr, props_ptr, prop_values_ptr, encoders_ptr;
};

/* ------------------------------------------------------------------ */
/* wire protocol                                                       */
/* ------------------------------------------------------------------ */

struct mmap_reply {
    uint64_t offset;
    uint64_t size;
    uint32_t pitch;
    uint32_t fourcc;
    uint32_t fb_id;
    uint32_t width;
    uint32_t height;
    uint32_t modifier_lo;
    uint32_t modifier_hi;
};

/* ------------------------------------------------------------------ */
/* capability drop + seccomp hardening                                 */
/* ------------------------------------------------------------------ */

struct cap_header {
    uint32_t version;
    int pid;
};

struct cap_data {
    uint32_t effective;
    uint32_t permitted;
    uint32_t inheritable;
};

#define _LINUX_CAPABILITY_VERSION_3 0x20080522
#define _LINUX_CAPABILITY_U32S_3 2

static void drop_capabilities(void) {
    struct cap_header hdr = {_LINUX_CAPABILITY_VERSION_3, 0};
    struct cap_data data[_LINUX_CAPABILITY_U32S_3];
    memset(&data, 0, sizeof(data));
    if (syscall(SYS_capset, &hdr, data) < 0) {
        fprintf(stderr, "capset failed: %s\n", strerror(errno));
    }
    if (prctl(PR_CAP_AMBIENT, PR_CAP_AMBIENT_CLEAR_ALL, 0, 0, 0) < 0) {
        fprintf(stderr, "prctl(PR_CAP_AMBIENT_CLEAR_ALL) failed: %s\n", strerror(errno));
    }
}

static void install_seccomp_filter(void) {
    struct sock_filter filter[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_X86_64, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 1, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 3, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 9, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 11, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 35, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 46, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 47, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 202, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 231, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL),
    };
    struct sock_fprog prog = {
        (unsigned short)(sizeof(filter) / sizeof(filter[0])),
        filter,
    };
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0) {
        fprintf(stderr, "prctl(PR_SET_NO_NEW_PRIVS) failed: %s\n", strerror(errno));
        return;
    }
    if (syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER, 0, &prog) < 0) {
        fprintf(stderr, "seccomp install failed: %s\n", strerror(errno));
    }
}

static void harden_after_init(void) {
    drop_capabilities();
    install_seccomp_filter();
}

/* ------------------------------------------------------------------ */
/* pidfd_getfd clone (Linux 5.6+)                                      */
/* ------------------------------------------------------------------ */

static int verify_kwin_process(pid_t pid) {
    char path[64];
    char link[256];
    snprintf(path, sizeof(path), "/proc/%d/exe", (int)pid);
    ssize_t len = readlink(path, link, sizeof(link) - 1);
    if (len < 0) {
        return -1;
    }
    link[len] = 0;
    if (strstr(link, "kwin_wayland") || strstr(link, "kwin_x11") || strstr(link, "kwin")) {
        return 0;
    }
    fprintf(stderr, "pid %d exe %s is not KWin\n", (int)pid, link);
    return -1;
}

static int pidfd_open(pid_t pid, unsigned int flags) {
    return syscall(434, pid, flags);
}

static int pidfd_getfd(int pidfd, int targetfd, unsigned int flags) {
    return syscall(438, pidfd, targetfd, flags);
}

static int clone_kwin_master_fd(const char *card_path, int *out_fd) {
    /* Find the KWin PID */
    FILE *f;
    char comm[64];
    pid_t kwin_pid = 0;

    for (int i = 0; i < 10000; i++) {
        char path[64];
        snprintf(path, sizeof(path), "/proc/%d/comm", i);
        f = fopen(path, "r");
        if (!f) continue;
        if (fgets(comm, sizeof(comm), f)) {
            comm[strcspn(comm, "\n")] = 0;
            if (!strcmp(comm, "kwin_wayland") || !strcmp(comm, "kwin_x11") ||
                !strcmp(comm, "kwin")) {
                kwin_pid = (pid_t)i;
                fclose(f);
                break;
            }
        }
        fclose(f);
    }
    if (kwin_pid == 0) {
        fprintf(stderr, "KWin process not found\n");
        return -1;
    }
    if (verify_kwin_process(kwin_pid) < 0) {
        return -1;
    }

    /* Iterate KWin's open fds looking for card_path */
    char fd_path[256];
    for (int fd_num = 0; fd_num < 512; fd_num++) {
        snprintf(fd_path, sizeof(fd_path), "/proc/%d/fd/%d", (int)kwin_pid, fd_num);
        char link[256];
        ssize_t len = readlink(fd_path, link, sizeof(link) - 1);
        if (len < 0) continue;
        link[len] = 0;
        if (strcmp(link, card_path) != 0) continue;

        int pidfd = pidfd_open(kwin_pid, 0);
        if (pidfd < 0) {
            fprintf(stderr, "pidfd_open(%d) failed: %s\n", (int)kwin_pid, strerror(errno));
            return -1;
        }
        int cloned = pidfd_getfd(pidfd, fd_num, 0);
        close(pidfd);
        if (cloned < 0) {
            fprintf(stderr, "pidfd_getfd(%d,%d) failed: %s\n", (int)kwin_pid, fd_num,
                    strerror(errno));
            return -1;
        }
        *out_fd = cloned;
        return 0;
    }

    fprintf(stderr, "KWin fd %s not found\n", card_path);
    return -1;
}

/* ------------------------------------------------------------------ */
/* FB discovery methods                                                 */
/* ------------------------------------------------------------------ */

static int find_fb_via_planes(int fd, uint32_t *out_fb_id) {
    struct drm_set_client_cap cap = {DRM_CLIENT_CAP_UNIVERSAL_PLANES, 1};
    if (ioctl(fd, DRM_IOCTL_SET_CLIENT_CAP, &cap) < 0) return -1;

    struct drm_mode_get_plane_res res;
    memset(&res, 0, sizeof(res));
    if (ioctl(fd, DRM_IOCTL_MODE_GETPLANERESOURCES, &res) < 0 || res.count_planes == 0) return -1;

    uint32_t *ids = malloc(res.count_planes * sizeof(uint32_t));
    if (!ids) return -1;
    res.plane_id_ptr = (uint64_t)(uintptr_t)ids;
    if (ioctl(fd, DRM_IOCTL_MODE_GETPLANERESOURCES, &res) < 0) {
        free(ids);
        return -1;
    }
    for (uint32_t i = 0; i < res.count_planes; i++) {
        struct drm_mode_get_plane pl;
        memset(&pl, 0, sizeof(pl));
        pl.plane_id = ids[i];
        if (ioctl(fd, DRM_IOCTL_MODE_GETPLANE, &pl) < 0) continue;
        if (pl.fb_id != 0) {
            *out_fb_id = pl.fb_id;
            free(ids);
            return 0;
        }
    }
    free(ids);
    return -1;
}

static int find_fb_via_crtc(int fd, uint32_t *out_fb_id) {
    struct drm_mode_card_res res;
    memset(&res, 0, sizeof(res));
    if (ioctl(fd, DRM_IOCTL_MODE_GETRESOURCES, &res) < 0 || res.count_crtcs == 0) return -1;

    size_t struct_sz = sizeof(res);
    uint8_t *blob = malloc(struct_sz + (size_t)res.count_crtcs * 4);
    if (!blob) return -1;
    memcpy(blob, &res, struct_sz);

    for (int pass = 0; pass < 2; pass++) {
        struct drm_mode_card_res *rp = (struct drm_mode_card_res *)blob;
        rp->crtc_id_ptr = (uint64_t)(uintptr_t)(blob + struct_sz);
        if (ioctl(fd, DRM_IOCTL_MODE_GETRESOURCES, blob) < 0) {
            free(blob);
            return -1;
        }
        uint32_t count = rp->count_crtcs;
        for (uint32_t i = 0; i < count; i++) {
            uint32_t cid;
            memcpy(&cid, blob + struct_sz + i * 4, 4);
            struct drm_mode_crtc crtc;
            memset(&crtc, 0, sizeof(crtc));
            crtc.crtc_id = cid;
            if (ioctl(fd, DRM_IOCTL_MODE_GETCRTC, &crtc) < 0) continue;
            if (crtc.fb_id != 0) {
                *out_fb_id = crtc.fb_id;
                free(blob);
                return 0;
            }
        }
        if (pass == 0) {
            uint32_t new_count = 0;
            memcpy(&new_count, blob + offsetof(struct drm_mode_card_res, count_crtcs), 4);
            if (new_count == 0) break;
        }
    }
    free(blob);
    return -1;
}

static int find_fb_via_getfb_brute(int fd, uint32_t *out_fb_id) {
    for (uint32_t fid = 1; fid <= 1024; fid++) {
        struct drm_mode_fb_cmd fb;
        memset(&fb, 0, sizeof(fb));
        fb.fb_id = fid;
        if (ioctl(fd, DRM_IOCTL_MODE_GETFB, &fb) < 0) continue;
        if (fb.width > 0 && fb.height > 0 && fb.handle != 0) {
            *out_fb_id = fid;
            return 0;
        }
    }
    return -1;
}

/* ------------------------------------------------------------------ */
/* FB export                                                            */
/* ------------------------------------------------------------------ */

static int map_dumb_handle(int fd, uint32_t handle, uint64_t *out_offset) {
    struct drm_mode_map_dumb req;
    memset(&req, 0, sizeof(req));
    req.handle = handle;
    if (ioctl(fd, DRM_IOCTL_MODE_MAP_DUMB, &req) < 0) return -1;
    *out_offset = req.offset;
    return 0;
}

static int export_framebuffer(int fd, uint32_t fb_id, struct mmap_reply *out, int *out_pass_fd,
                               int *out_close_pass_fd) {
    struct drm_mode_fb_cmd2 fb2;
    memset(&fb2, 0, sizeof(fb2));
    fb2.fb_id = fb_id;

    int ret = ioctl(fd, DRM_IOCTL_MODE_GETFB2, &fb2);

    /* Fallback: use legacy GETFB to get handle, then fake fb2 fields */
    struct drm_mode_fb_cmd fb_legacy;
    uint32_t handle;
    if (ret < 0) {
        memset(&fb_legacy, 0, sizeof(fb_legacy));
        fb_legacy.fb_id = fb_id;
        if (ioctl(fd, DRM_IOCTL_MODE_GETFB, &fb_legacy) < 0) {
            fprintf(stderr, "GETFB2 + GETFB both failed for fb %u: %s\n", fb_id, strerror(errno));
            return -1;
        }
        handle = fb_legacy.handle;
        out->pitch = fb_legacy.pitch;
        out->fourcc = 0; /* unknown from legacy GETFB */
        out->width = fb_legacy.width;
        out->height = fb_legacy.height;
        out->offset = 0;
        out->modifier_lo = 0;
        out->modifier_hi = 0;
    } else {
        handle = fb2.handles[0];
        if (handle == 0) {
            fprintf(stderr, "GETFB2 returned zero handle\n");
            return -1;
        }
        uint64_t mod = fb2.modifier[0];
        out->offset = (uint64_t)fb2.offsets[0];
        out->pitch = fb2.pitches[0];
        out->fourcc = fb2.pixel_format;
        out->width = fb2.width;
        out->height = fb2.height;
        out->modifier_lo = (uint32_t)(mod & 0xffffffffU);
        out->modifier_hi = (uint32_t)(mod >> 32);
    }

    out->fb_id = fb_id;

    /* Try PRIME_HANDLE_TO_FD first (DMA-BUF) */
    struct drm_prime_handle prime;
    memset(&prime, 0, sizeof(prime));
    prime.handle = handle;
    prime.flags = DRM_CLOEXEC;
    prime.fd = -1;
    if (ioctl(fd, DRM_IOCTL_PRIME_HANDLE_TO_FD, &prime) == 0 && prime.fd >= 0) {
        out->size = (uint64_t)out->pitch * (uint64_t)out->height;
        out->offset = 0;
        *out_pass_fd = prime.fd;
        *out_close_pass_fd = 1;
        return 0;
    }

    /* Fallback: GEM_FLINK → GEM_OPEN → MAP_DUMB → mmap */
    struct drm_gem_flink flink;
    memset(&flink, 0, sizeof(flink));
    flink.handle = handle;
    if (ioctl(fd, DRM_IOCTL_GEM_FLINK, &flink) < 0) {
        fprintf(stderr, "GEM_FLINK failed: %s\n", strerror(errno));
        /* Last resort: try MAP_DUMB directly on the GETFB handle */
        uint64_t map_off2 = 0;
        if (map_dumb_handle(fd, handle, &map_off2) == 0) {
            fprintf(stderr, "MAP_DUMB fallback succeeded\n");
        out->offset = map_off2;
        out->size = (uint64_t)out->pitch * (uint64_t)out->height;
        *out_pass_fd = fd;
        *out_close_pass_fd = 0;
        return 0;
        }
        fprintf(stderr, "PRIME+GEM_FLINK+MAP_DUMB all failed for fb %u\n", fb_id);
        return -1;
    }

    struct drm_gem_open open_req;
    memset(&open_req, 0, sizeof(open_req));
    open_req.name = flink.name;
    if (ioctl(fd, DRM_IOCTL_GEM_OPEN, &open_req) < 0) {
        fprintf(stderr, "GEM_OPEN failed: %s\n", strerror(errno));
        return -1;
    }

    uint64_t map_off = 0;
    if (map_dumb_handle(fd, open_req.handle, &map_off) < 0) {
        fprintf(stderr, "MAP_DUMB failed: %s\n", strerror(errno));
        return -1;
    }

    out->offset = map_off;
    out->size = (uint64_t)out->pitch * (uint64_t)out->height;
    *out_pass_fd = fd;
    *out_close_pass_fd = 0;
    return 0;
}

/* ------------------------------------------------------------------ */
/* send reply via Unix socket + SCM_RIGHTS                             */
/* ------------------------------------------------------------------ */

static int send_reply(int sock, int pass_fd, const struct mmap_reply *reply) {
    char control[CMSG_SPACE(sizeof(int))];
    memset(control, 0, sizeof(control));
    struct iovec iov = {(void *)reply, sizeof(*reply)};
    struct msghdr msg = {NULL, 0, &iov, 1, control, sizeof(control), 0};
    struct cmsghdr *cmsg = CMSG_FIRSTHDR(&msg);
    cmsg->cmsg_level = SOL_SOCKET;
    cmsg->cmsg_type = SCM_RIGHTS;
    cmsg->cmsg_len = CMSG_LEN(sizeof(int));
    memcpy(CMSG_DATA(cmsg), &pass_fd, sizeof(pass_fd));
    msg.msg_controllen = cmsg->cmsg_len;

    if (sendmsg(sock, &msg, 0) < 0) {
        fprintf(stderr, "sendmsg failed: %s\n", strerror(errno));
        return -1;
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/* main                                                                 */
/* ------------------------------------------------------------------ */

int main(int argc, char **argv) {
    if (argc != 4) {
        fprintf(stderr, "usage: %s <card_path> <unix_socket_path> <fb_id>\n", argv[0]);
        return 2;
    }

    const char *card_path = argv[1];
    const char *sock_path = argv[2];
    uint32_t fb_id = (uint32_t)strtoul(argv[3], NULL, 10);

    int card_fd = open(card_path, O_RDWR | O_CLOEXEC);
    if (card_fd < 0) {
        fprintf(stderr, "open %s failed: %s\n", card_path, strerror(errno));
        return 1;
    }

    int is_master_fd = 0;
    (void)is_master_fd;

    /* Try fresh open + planes (works on AMD/Intel) */
    if (fb_id == 0) {
        if (find_fb_via_planes(card_fd, &fb_id) == 0) {
            /* found on fresh fd */
        } else if (find_fb_via_crtc(card_fd, &fb_id) == 0) {
            /* found via CRTC on fresh fd */
        }
    }

    /* If fresh fd failed, try cloned master fd (NVIDIA) */
    if (fb_id == 0) {
        int master_fd = -1;
        if (clone_kwin_master_fd(card_path, &master_fd) == 0) {
            fprintf(stderr, "using cloned KWin master fd\n");
            close(card_fd);
            card_fd = master_fd;
            is_master_fd = 1;

            /* Try planes on master fd */
            if (find_fb_via_planes(card_fd, &fb_id) < 0) {
                /* Try CRTC on master fd */
                if (find_fb_via_crtc(card_fd, &fb_id) < 0) {
                    /* Last resort: brute-force GETFB on master fd */
                    fprintf(stderr, "trying brute-force GETFB on master fd\n");
                    if (find_fb_via_getfb_brute(card_fd, &fb_id) < 0) {
                        fprintf(stderr, "no active framebuffer found (all methods)\n");
                        close(card_fd);
                        return 1;
                    }
                }
            }
        } else {
            fprintf(stderr, "no active framebuffer found (all methods, KWin clone failed)\n");
            close(card_fd);
            return 1;
        }
    }

    struct mmap_reply reply;
    int pass_fd = -1;
    int close_pass_fd = 0;
    if (export_framebuffer(card_fd, fb_id, &reply, &pass_fd, &close_pass_fd) < 0) {
        close(card_fd);
        return 1;
    }

    int sock = socket(AF_UNIX, SOCK_STREAM, 0);
    if (sock < 0) {
        fprintf(stderr, "socket failed: %s\n", strerror(errno));
        if (close_pass_fd) close(pass_fd);
        close(card_fd);
        return 1;
    }

    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, sock_path, sizeof(addr.sun_path) - 1);
    if (connect(sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        fprintf(stderr, "connect %s failed: %s\n", sock_path, strerror(errno));
        close(sock);
        if (close_pass_fd) close(pass_fd);
        close(card_fd);
        return 1;
    }

    harden_after_init();

    int rc = send_reply(sock, pass_fd, &reply);
    close(sock);
    if (close_pass_fd) close(pass_fd);
    close(card_fd);
    return rc == 0 ? 0 : 1;
}
