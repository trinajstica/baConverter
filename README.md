# baConverter

baConverter is a simple GTK application for converting video and audio files using FFmpeg. It provides an easy-to-use graphical interface for selecting input files, choosing codecs, output formats, and performing batch conversions.

## Features

- Convert single or multiple media files
- Support for various audio and video codecs
- Batch processing with drag-and-drop support
- Automatic codec detection from input files
- Real-time conversion progress and logging
- Modern GTK4 interface with libadwaita

## Dependencies

- GTK4 (>= 4.8)
- libadwaita-1
- json-glib-1.0
- FFmpeg (with ffprobe)
- Meson (>= 0.60.0)

### Solus (Linux)

Solus uses different package names and provides separate `-devel` packages for headers and pkg-config metadata. For development (building from source) install the runtime and development packages below.

Recommended (build + runtime):

```bash
sudo eopkg install -y libgtk-4 libgtk-4-devel libadwaita libadwaita-devel \
   libjson-glib libjson-glib-devel ffmpeg ffmpeg-devel meson ninja ccache \
   pkgconf pkgconf-devel gcc make
```

If you only need to run the already-built application (no compilation), you can install the runtime packages:

```bash
sudo eopkg install -y libgtk-4 libadwaita libjson-glib ffmpeg pkgconf
```

Notes:
- `pkgconf` provides the `pkg-config` functionality on Solus; use `pkgconf-devel` for development files.
- If you run into missing headers during compile, search for the corresponding `-devel` package with `eopkg search <library>` and install it.

## Building

1. Ensure you have all dependencies installed. On Ubuntu/Debian:
   ```
   sudo apt install libgtk-4-dev libadwaita-1-dev libjson-glib-dev ffmpeg meson ninja-build
   ```

2. Clone or download the source code.

3. Navigate to the project directory:
   ```
   cd baConverter
   ```

4. Configure the build:
   ```
   meson setup build
   ```

5. Build the project:
   ```
   meson compile -C build
   ```

## Installation

To install the application system-wide:

```
meson install -C build
```

This will install the executable (`bac`), desktop file, and icons.

## Usage

After installation, you can launch baConverter from your application menu or run `bac` from the terminal.

### Single File Conversion

1. Click "Choose File" to select an input media file.
2. Select desired output format and codecs.
3. Optionally adjust audio/video settings.
4. Click "Start" to begin conversion.
5. Monitor progress in the log area.

### Batch Conversion

1. Click "Batch" to open the batch processing dialog.
2. Add files or folders using the buttons or drag-and-drop.
3. Configure output settings as needed.
4. Click "Start batch" to process all files.

### Settings

- **Format**: Choose output container format (auto, mp4, mkv, etc.)
- **Audio/Video Codecs**: Select encoders or choose "Copy" to preserve original
- **Copy checkboxes**: When checked, streams are copied without re-encoding

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.