#!/usr/bin/env bash
# helper script to install development dependencies for baConverter on common distros
# Usage: sudo ./scripts/setup-dev.sh  OR ./scripts/setup-dev.sh --print (to only print commands)

set -euo pipefail

PRINT_ONLY=0
if [ "${1:-}" = "--print" ] || [ "${1:-}" = "-n" ]; then
  PRINT_ONLY=1
fi

cmd() {
  if [ "$PRINT_ONLY" -eq 1 ]; then
    echo "+ $*"
  else
    echo "+ $*"; eval "$@"
  fi
}

if [ -f /etc/os-release ]; then
  . /etc/os-release
else
  echo "Cannot detect distribution (no /etc/os-release). Exiting." >&2
  exit 1
fi

pkgs_meson_common="meson ninja gcc pkgconf libjson-glib-devel libgtk-4-devel libadwaita-devel ffmpeg"
# Map common package names for distributions where -devel suffix differs
case "${ID_LIKE:-}${ID:-}" in
  *debian*|*ubuntu*|debian|ubuntu)
    echo "Detected Debian/Ubuntu"
    install_cmds=(
      "apt update"
      "apt install -y build-essential ${pkgs_meson_common//-devel/}-dev pkg-config"
    )
    ;;
  *fedora*|fedora)
    echo "Detected Fedora"
    install_cmds=(
      "dnf install -y meson ninja-build @development-tools pkgconfig libadwaita-devel gtk4-devel json-glib-devel ffmpeg"
    )
    ;;
  *arch*|arch|manjaro)
    echo "Detected Arch/Manjaro"
    install_cmds=(
      "pacman -Syu --noconfirm meson ninja base-devel pkgconf libadwaita gtk4 json-glib ffmpeg"
    )
    ;;
  *solus*|solus)
    echo "Detected Solus"
    # Solus uses eopkg; package names may vary between repo versions
    install_cmds=(
      "eopkg update-repo"
      "eopkg install -y meson ninja gcc pkgconf libjson-glib-devel ffmpeg libgtk-4-devel libadwaita-devel"
    )
    ;;
  *suse*|opensuse)
    echo "Detected openSUSE"
    install_cmds=(
      "zypper refresh"
      "zypper install -y meson ninja gcc pkg-config libadwaita-devel gtk4-devel libjson-glib-devel ffmpeg"
    )
    ;;
  *)
    echo "Unknown or unsupported distribution: $ID. I'll show generic instructions instead." >&2
    install_cmds=(
      "# Generic: install Meson, Ninja, a C compiler, pkg-config and development headers for libadwaita/gtk4/json-glib and ffmpeg"
      "# Debian-like: sudo apt install -y build-essential meson ninja-build pkg-config libadwaita-1-dev libgtk-4-dev libjson-glib-dev ffmpeg"
      "# Fedora: sudo dnf install -y meson ninja-build @development-tools pkgconfig libadwaita-devel gtk4-devel json-glib-devel ffmpeg"
      "# Arch: sudo pacman -Syu meson ninja base-devel pkgconf libadwaita gtk4 json-glib ffmpeg"
      "# Solus: sudo eopkg update-repo && sudo eopkg install -y meson ninja gcc pkgconf libjson-glib-devel ffmpeg libgtk-4-devel libadwaita-devel"
    )
    ;;
esac

echo "\n== About to run/install the following (run as root or with sudo) =="
for c in "${install_cmds[@]}"; do
  echo "$c"
done

if [ "$PRINT_ONLY" -eq 1 ]; then
  echo "\n-- printed commands only (--print) --"; exit 0
fi

echo "\n== Running install commands =="
for c in "${install_cmds[@]}"; do
  if [[ "$c" =~ ^# ]]; then
    echo "$c"; continue
  fi
  if command -v sudo >/dev/null 2>&1; then
    cmd "sudo $c"
  else
    cmd "$c"
  fi
done

echo "\nDone. Verify Meson with: meson --version"
