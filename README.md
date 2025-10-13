# baConvert

Minimal GNOME libadwaita application skeleton named "baConvert".

Executable: bac

Requirements
- meson >= 0.60
- ninja
- libadwaita-1 (development files)
- gtk4 (development files)

Build

1. meson setup build
2. meson compile -C build

Run

./build/bac

Install

meson install -C build

Where build artifacts go

- The Meson build directory is `build/`. Compiled binaries are placed there (e.g. `build/bac`).
- Installed files (when running `sudo meson install -C build`) are copied to system locations such as `/usr/local/bin` and `/usr/local/share/applications` (desktop entry) and `/usr/local/share/icons/hicolor/...` (icons).

Reproducible steps (example)

```sh
# configure
meson setup --reconfigure build
# build
ninja -C build
# run
./build/bac
```

Notes
- This is a minimal, monolithic C app using libadwaita/GTK4. Window default size is 800x600 and is resizable (responsive). Follow GNOME Human Interface Guidelines and libadwaita styles when adding UI.
