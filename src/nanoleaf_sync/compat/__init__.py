"""KDE/Plasma compatibility probing and version change detection."""

from nanoleaf_sync.compat.kde_version import (
    format_version_tuple,
    get_kwin_version,
    get_plasma_version,
)
from nanoleaf_sync.compat.kwin_probe import (
    get_screenshot2_api_version,
    get_screenshot2_capabilities,
    log_kwin_probe_results,
    reset_kwin_probe_cache,
)
from nanoleaf_sync.compat.portal_probe import (
    get_portal_capabilities,
    get_portal_version,
    log_portal_probe_results,
    reset_portal_probe_cache,
    supports_pipewire_serial,
)
from nanoleaf_sync.compat.update_checker import (
    UpdateCheckResult,
    check_for_updates,
    default_cache_path,
    manual_check_message,
    mark_update_notified,
    should_notify_for_update,
    update_notification_message,
)
from nanoleaf_sync.compat.version_snapshot import (
    check_for_upgrade,
    collect_current_versions,
    default_snapshot_path,
    update_snapshot,
)

__all__ = (
    "UpdateCheckResult",
    "check_for_updates",
    "check_for_upgrade",
    "collect_current_versions",
    "default_cache_path",
    "default_snapshot_path",
    "manual_check_message",
    "mark_update_notified",
    "should_notify_for_update",
    "update_notification_message",
    "format_version_tuple",
    "get_kwin_version",
    "get_plasma_version",
    "get_portal_capabilities",
    "get_portal_version",
    "get_screenshot2_api_version",
    "get_screenshot2_capabilities",
    "log_kwin_probe_results",
    "log_portal_probe_results",
    "reset_kwin_probe_cache",
    "reset_portal_probe_cache",
    "supports_pipewire_serial",
    "update_snapshot",
)
