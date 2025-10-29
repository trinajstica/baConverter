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