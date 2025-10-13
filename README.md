# baConverter

Minimal GNOME libadwaita application skeleton named "baConverter".

Executable: bac

Requirements
- meson >= 0.60
- ninja
- libadwaita-1 (development files)
- gtk4 (development files)
 - ffmpeg (optional, required for actual media conversion at runtime)

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

Why use baConverter?

baConverter is a lightweight, straightforward desktop tool for converting multimedia files on GNOME. It targets users who want to:

- quickly transcode video or audio without writing complex command lines;
- keep or drop audio/video streams using the "copy" option to preserve original quality or to export quickly without re-encoding;
- export files into common containers (MP4, MKV, WebM, etc.) with sensible default encoder choices;
- integrate with the GNOME desktop (desktop entry, icons) so the tool is discoverable from the applications menu or shell search.

For developers, baConverter also:

- serves as a compact example of using libadwaita/GTK4 in C to build a simple GUI tool;
- demonstrates invoking external programs (ffmpeg/ffprobe) and parsing their output to update the UI.

Common scenarios include quickly converting mobile phone recordings, preparing files for web delivery, or reducing file sizes for sharing.

Dependencies and how to install (if you don't have them)

This project depends on Meson, Ninja and development packages for libadwaita, GTK4 and json-glib. The commands below install the required packages on common distributions.

- Debian/Ubuntu (example):

```sh
sudo apt update
sudo apt install -y build-essential meson ninja-build libadwaita-1-dev libgtk-4-dev libjson-glib-dev ffmpeg
```

- Fedora (example):

```sh
sudo dnf install -y meson ninja-build @development-tools libadwaita-devel gtk4-devel json-glib-devel ffmpeg
```

- Arch/Manjaro (example):

```sh
sudo pacman -Syu meson ninja base-devel libadwaita gtk4 json-glib ffmpeg
```

Build, install and uninstall

```sh
# configure (run once, or use --reconfigure to update)
meson setup --reconfigure build
# build
ninja -C build
# run locally
./build/bac
# install system-wide (may require sudo)
sudo ninja -C build install
# uninstall (from same build dir)
sudo ninja -C build uninstall
```

Cleaning up

- To remove the local build directory and generated files:

```sh
rm -rf build/
rm -f compile_commands.json
```

- To remove installed files after `meson install` if `ninja uninstall` did not remove everything, check `/usr/local/bin`, `/usr/local/share/applications` and `/usr/local/share/icons/hicolor/` and manually remove the `bac` binary and installed desktop/icon files.
