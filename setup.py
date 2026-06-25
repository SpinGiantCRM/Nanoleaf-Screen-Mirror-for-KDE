"""Build hooks for platform-specific wheels.

The package ships a native ``nanoleaf_drm_helper`` binary, so release wheels
must be tagged ``linux_x86_64`` instead of ``py3-none-any``.
"""

from setuptools import setup

try:
    from wheel.bdist_wheel import bdist_wheel as _bdist_wheel
except ImportError:  # pragma: no cover - wheel is a build dependency
    from setuptools.command.bdist_wheel import bdist_wheel as _bdist_wheel


class bdist_wheel(_bdist_wheel):
    """Force linux_x86_64 wheel tags for the bundled DRM helper binary."""

    def finalize_options(self) -> None:
        super().finalize_options()
        self.root_is_pure = False

    def get_tag(self) -> tuple[str, str, str]:
        python, abi, _plat = super().get_tag()
        return python, abi, "linux_x86_64"


setup(cmdclass={"bdist_wheel": bdist_wheel})
