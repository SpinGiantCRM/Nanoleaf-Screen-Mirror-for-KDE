# Operator tools

## Screen-to-strip response target

Open `latency-pattern.html` in a normal browser on the same monitor selected in
Nanoleaf. This is a local, self-contained file: no server, internet, camera access
or app integration is required. Start mirroring through the normal tray using
your saved configuration. The page itself never opens USB or changes settings.

With the camera recording both the monitor and strip, press **Start full-screen
test**. After a three-second countdown, the screen holds grey, white, black, red,
blue and grey for two seconds each. Controls disappear during the twelve-second
sequence so they do not contaminate sampled zones. Esc, hiding the page or ending
the sequence stops it. Stop mirroring through the tray when finished if desired.

Use 120/240 fps recording when available, a steady camera, and an exposure that
retains both the screen transition and individual LED changes without clipping.
Lock exposure/white balance if possible. Keep the chosen screen and LED reference
areas near the same vertical position in the camera image to reduce rolling-
shutter timing differences. No enclosure access or firmware changes are needed.

Record the actual camera acquisition rate: some slow-motion exports play at
30 fps while containing 120/240 fps acquisition. File playback rate alone is not
proof of acquisition rate. Frame differences correspond to about 8.33 ms at
120 fps or 4.17 ms at 240 fps, with additional exposure/rolling-shutter uncertainty.
Ordinary video provides coarser bounds and may not resolve the USB delay.

Analysis should compare the first visible screen change with the first and settled
strip changes across several transitions. Browser timer/RAF times are not photon
timestamps. Neither this target nor a colour camera replaces a colorimeter or
photodiode. No optical measurement is claimed until a real recording is analysed.
