# Warframe capture hang investigation — 4 November 2026

## Finding

The observed failure is a GPU context-switch timeout. The capture trigger has
not been established, and no gameplay fix is claimed.

At **18:13:11** and **20:46:10 ACDT**, the kernel reported NVIDIA **Xid 109,
CTX SWITCH TIMEOUT**, naming Warframe. At the same times, KWin reported failures
to allocate swapchain graphics buffers. Warframe's second-session log recorded
a 2295 ms Present budget overrun approximately one second after the timeout.
The user confirmed the game was frozen during inspection.

The Nanoleaf tray process survived. Its portal/Vulkan capture helper had exited,
and the service reported that fresh capture frames stalled and an explicit Start
was required. The simultaneous symptoms therefore do not demonstrate that the
Nanoleaf application process crashed or establish which component triggered the
GPU hang. KWin and the NVIDIA management interface still answered bounded queries.

No OOM kill or systemd-oomd event was found in the available journal. Retained
journal coverage is principally this boot; this is not an exhaustive historical
exclusion. The inspected environment used NVIDIA 615.78.08, an RTX 4080 SUPER,
KDE Plasma 6.8 and Warframe's D3D12 renderer.

[NVIDIA identifies Xid 109 as a context-switch timeout](https://docs.nvidia.com/deploy/xid-errors/analyzing-xid-catalog.html).
[Its diagnostic guidance](https://docs.nvidia.com/deploy/xid-errors/introduction.html)
explains that an Xid alone cannot distinguish an application, driver or hardware
root cause.

## Temporary comparison and its limits

The user's saved backend was already **xdg-portal / Vulkan**, with Target FPS 240,
normal process priority and 48 manual zones. It remains selected. KWin was used
only for a temporary comparison, not as a new default or a performance upgrade.

A private copy of the configuration changed only the capture backend. The
installed application's KWin capture-only probe ran in 28 completed 30-second
batches: **840.37 seconds and 36,862 frames at 3840 × 2160**, with no new Xid found
during that interval. The final partial batch was deliberately terminated by the
operator, not classified as an application failure. No screen pixels were saved
and no USB lighting output was driven.

The user subsequently confirmed they **had not been actively playing**. This is
an idle-game comparison, not a gameplay stability pass. Short gaps between probe
processes, different capture implementations and their actual delivered cadence
also limit comparison. The preceding hang occurred about 17 minutes into its game
session. These observations do not qualify KWin as a fix, prove Vulkan caused
the hang, or establish that a later app/helper build is stable in Warframe.

## Next useful evidence

Compare the same active Warframe scene with no capture, portal/Vulkan capture,
and KWin capture. Keep game graphics, overlays, driver, display settings, manual
zone count and Target FPS unchanged; retain the same app/helper build across
conditions. Use private copied configurations and bounded trials. Correlate the
first kernel Xid, game Present/device errors and capture helper termination.

Keep capture-only trials separate from USB output. Any later physical-output
trial must have exclusive ownership and verify controller power/brightness
restoration. Preserve the saved backend unless the user chooses a workaround.
Do not change graphics drivers, game renderer, synchronization mode or capture
defaults based on this idle comparison.

Raw game logs and configuration snapshots are private operator evidence and are
not included in the repository. Existing unrelated firmware research is preserved.

## New-build gameplay follow-up

After the idle comparison, the tested new app/helper bundle was installed with
the previous native pair retained. Configuration and calibration were restored
byte-for-byte and the saved portal/Vulkan backend was retained. The user asked
to continue testing during active gameplay and report back if another hang occurs.
The normal application was started on that Vulkan backend, with a separate private
recorder sampling service/process state every two seconds and preserving GPU/game
logs on detected incidents. The recorder does not change capture, FPS, priority,
display or game settings. Recording continues until explicitly stopped or the
session ends; its presence is not a claim that gameplay stability has passed.


## Recorded recurrence at 22:53 ACDT

The recorder captured another NVIDIA Xid109 naming Warframe at **22:53:06.486**.
KWin reported that its main thread had hung at **22:53:06.495**, then reported
swapchain buffer-allocation failures. The game log recorded a **2472 ms Present
budget overrun** at approximately the same time. That run used GE-Proton11-12,
D3D12 and borderless 3840×2160, and had run about 39 minutes. Earlier testing used
a different Proton build, so the sessions are not a controlled Proton comparison.

Nanoleaf's last running sample was at **22:53:02.543**, with 318,302 acknowledged
updates. At **22:53:04.556** it was stopped because desktop-session monitoring was
unavailable; at **22:53:06.643** session monitoring had recovered, but mirroring
correctly remained stopped pending an explicit Start. The tray process survived.
The session monitor queries KWin's ScreenSaver service with a two-second timeout,
so an unresponsive compositor can explain this stop without a Nanoleaf crash.
The exact query failure was not logged; this explanation remains an inference.
The driver report and buffered game log do not establish exact hang onset or
whether capture triggered the GPU fault.

The same recording also caught Xid31 faults naming the launcher at **22:03:56**
and Warframe at **22:09:00**, followed by launcher graphics/channel faults
(Xid13/32) at **22:12:41–51**. Nanoleaf continued mirroring through those earlier
events. No system OOM kill was found. The new failure-report/notification bundle
was still uninstalled, preserving the build under test. Raw logs and a separate
post-incident game-log copy are retained privately; the recorder remains running.
