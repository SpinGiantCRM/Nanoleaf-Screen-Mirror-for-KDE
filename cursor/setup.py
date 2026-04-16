from setuptools import find_packages, setup


setup(
    name="nanoleaf-kde-sync",
    version="0.0.0",
    python_requires=">=3.11",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    entry_points={
        "console_scripts": [
            "nanoleaf-kde-sync=nanoleaf_sync.ui.tray:main",
            "nanoleaf-kde-sync-service=nanoleaf_sync.runtime.service:main",
        ],
    },
    install_requires=[
        "numpy>=1.21",
        "PyQt6>=6.0",
        "dbus-next>=0.2.0",
        "hidapi>=0.14.0",
    ],
)
