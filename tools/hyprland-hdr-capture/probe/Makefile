PROTOCOLS := $(shell pkg-config --variable=pkgdatadir wayland-protocols)/staging
SCANNER   := $(shell pkg-config --variable=wayland_scanner wayland-scanner)

CFLAGS ?= -O2 -Wall -Wextra
GENERATED = ext-image-capture-source-v1-client-protocol.h ext-image-capture-source-v1-protocol.c \
            ext-image-copy-capture-v1-client-protocol.h ext-image-copy-capture-v1-protocol.c \
            ext-foreign-toplevel-list-v1-protocol.c

STABLE := $(shell pkg-config --variable=pkgdatadir wayland-protocols)/stable

all: nanoleaf-hdr-probe nanoleaf-hdr-ladder

color-management-v1-client-protocol.h:
	$(SCANNER) client-header $(PROTOCOLS)/color-management/color-management-v1.xml $@
color-management-v1-protocol.c:
	$(SCANNER) private-code $(PROTOCOLS)/color-management/color-management-v1.xml $@
xdg-shell-client-protocol.h:
	$(SCANNER) client-header $(STABLE)/xdg-shell/xdg-shell.xml $@
xdg-shell-protocol.c:
	$(SCANNER) private-code $(STABLE)/xdg-shell/xdg-shell.xml $@

# Test pattern: known PQ luminances in a colour-managed window.
nanoleaf-hdr-ladder: hdr-ladder.c color-management-v1-client-protocol.h color-management-v1-protocol.c xdg-shell-client-protocol.h xdg-shell-protocol.c
	$(CC) $(CFLAGS) -Wno-incompatible-pointer-types -Wno-strict-prototypes -o $@ hdr-ladder.c \
		color-management-v1-protocol.c xdg-shell-protocol.c `pkg-config --cflags --libs wayland-client` -lm

ext-image-capture-source-v1-client-protocol.h:
	$(SCANNER) client-header $(PROTOCOLS)/ext-image-capture-source/ext-image-capture-source-v1.xml $@
ext-image-capture-source-v1-protocol.c:
	$(SCANNER) private-code $(PROTOCOLS)/ext-image-capture-source/ext-image-capture-source-v1.xml $@
ext-image-copy-capture-v1-client-protocol.h:
	$(SCANNER) client-header $(PROTOCOLS)/ext-image-copy-capture/ext-image-copy-capture-v1.xml $@
ext-image-copy-capture-v1-protocol.c:
	$(SCANNER) private-code $(PROTOCOLS)/ext-image-copy-capture/ext-image-copy-capture-v1.xml $@

# Referenced by the capture-source protocol's toplevel source interface.
ext-foreign-toplevel-list-v1-protocol.c:
	$(SCANNER) private-code $(PROTOCOLS)/ext-foreign-toplevel-list/ext-foreign-toplevel-list-v1.xml $@

nanoleaf-hdr-probe: probe.c $(GENERATED)
	$(CC) $(CFLAGS) -Wno-incompatible-pointer-types -Wno-strict-prototypes -o $@ probe.c \
		ext-image-capture-source-v1-protocol.c ext-image-copy-capture-v1-protocol.c ext-foreign-toplevel-list-v1-protocol.c \
		`pkg-config --cflags --libs wayland-client` -lm

clean:
	rm -f nanoleaf-hdr-probe nanoleaf-hdr-ladder $(GENERATED) color-management-v1-* xdg-shell-*

.PHONY: all clean
