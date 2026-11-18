# Build against the headers of the Hyprland that will load the plugin.
# Hyprland plugins have no ABI stability: rebuild after every Hyprland update.

ifeq ($(CXX),g++)
    EXTRA_FLAGS = --no-gnu-unique
else
    EXTRA_FLAGS =
endif

CXXFLAGS ?= -O2 -Wall
CXXFLAGS += -shared -fPIC -std=c++2b

all: nanoleaf-hdr.so

nanoleaf-hdr.so: main.cpp
	$(CXX) $(CXXFLAGS) $(LDFLAGS) $(EXTRA_FLAGS) main.cpp -o $@ \
		`pkg-config --cflags pixman-1 libdrm hyprland pangocairo libinput libudev wayland-server xkbcommon`

clean:
	rm -f nanoleaf-hdr.so

.PHONY: all clean
