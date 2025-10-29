# baConverter

Minimalna GNOME libadwaita aplikacija z imenom "baConverter".

Izvedljiva datoteka: `bac`

Opis
-----
baConverter je preprosto namizno orodje za pretvarjanje multimedijskih datotek, napisano v jeziku C z uporabo libadwaita/GTK4. Namenjeno je hitremu in enostavnemu transkodiranju ali kopiranju tokov brez zahtevnega ukaznega vrstice.

Zahteve (kratko)
-----------------
- Meson (>=0.60 priporočeno)
- Ninja
- C compiler (gcc/clang)
- libadwaita, GTK4, json-glib (razvojne knjižnice za gradnjo)
- ffmpeg (opcijsko, za dejansko pretvarjanje medijskih datotek)

Namestitev odvisnosti po distribucijah
-------------------------------------
Spodaj so primeri ukazov za namestitev potrebnih paketov na priljubljenih distribucijah. Prilagodi ukaze glede na tvojo distribucijo in verzije paketov.

- Debian / Ubuntu (primer):

```sh
sudo apt update
sudo apt install -y build-essential meson ninja-build pkg-config libadwaita-1-dev libgtk-4-dev libjson-glib-dev ffmpeg
```

- Fedora (primer):

```sh
sudo dnf install -y meson ninja-build @development-tools pkgconfig libadwaita-devel gtk4-devel json-glib-devel ffmpeg
```

- Arch / Manjaro (primer):

```sh
sudo pacman -Syu meson ninja base-devel pkgconf libadwaita gtk4 json-glib ffmpeg
```

- Solus (primer):

```sh
# osveži lokalne repozitorije
sudo eopkg update-repo
# namešči razvojne in runtime pakete
sudo eopkg install -y meson ninja gcc pkgconf libjson-glib-devel ffmpeg libgtk-4-devel libadwaita-devel
```

Opombe za Solus
---------------
- Na Solusu je priporočljivo poskrbeti, da je nameščen `pkgconf` ali `pkg-config` (odvisno od imena paketa v repozitoriju). Če je Meson v sistemskih repozitorijih prepočasen, ga lahko nadomestiš z:

```sh
pipx install meson
# ali
pip3 install --user meson
```

Gradnja
-------
1. Konfiguracija gradnje (ustvari build dir):

```sh
meson setup --buildtype=release build
```

Če si že imel build direktorij in želiš prekonfigurirati:

```sh
meson setup --reconfigure build
```

2. Gradnja (ninja backend):

```sh
meson compile -C build
# ali neposredno z ninja
ninja -C build
```

3. Izvedba zgrajenega programa (iz projektne mape):

```sh
./build/src/bac
```

Namestitev
----------
Za sistemsko namestitev:

```sh
sudo meson install -C build
# ali
sudo ninja -C build install
```

Odstranitev namestitve:

```sh
sudo ninja -C build uninstall
```

Kje so artefakti
----------------
- Meson build dir: `build/`
- Izvedljiva datoteka: `build/src/bac` (lokalno)
- Compile database: `build/compile_commands.json`
- Meson metapodatki: `build/meson-info/`, `build/meson-logs/`, `build/meson-private/`

Ponovljiv postopek (primer)
---------------------------

```sh
# odstranite build, če želite čisto stanje
rm -rf build/
# konfigurirajte in zgradite
meson setup --buildtype=release build
meson compile -C build
./build/src/bac
```

Kratke opombe o runtime odvisnostih
----------------------------------
- Program potrebuje knjižnice libadwaita (libadwaita-1), GTK4 in json-glib za zagon GUI.
- Za pretvarjanje multimedijskih datotek potrebuješ `ffmpeg` (ali drugo orodje), sicer bodo nekatere funkcije omejene.

Reševanje težav
----------------
- Če meson javi, da je potrebna višja verzija, posodobi Meson (poglej zgoraj Solus opombo za pipx/pip3).
- Če se povezovanje ne uspe (linker errors), preveri, da so nameščene razvojne verzije knjižnic (`-devel` or `-dev` paketi).
- Opozorila o zastarelih GTK funkcijah so običajno varna — delovanje ne bo prekinjeno, a razmisli o posodobitvi API klicev.

Urejanje in razvoj
------------------
- Koda uporablja meson kot sistem za gradnjo in je primerna za hitro razvojno iteracijo z `meson setup --reconfigure build` in `meson compile -C build`.
- Če želiš debug build, uporabi `--buildtype=debug` ali `--buildtype=debugoptimized` pri `meson setup`.

Čiščenje
--------

```sh
rm -rf build/
rm -f compile_commands.json
```

Licenca
-------
Oglej si `LICENSE` datoteko v repozitoriju za pogoje licenciranja.

```# baConverter

Minimal GNOME libadwaita application skeleton named "baConverter".

Executable: bac

Requirements

Za Solus Linux namesti vse potrebne pakete za razvoj in zagon z eno samo vrstico:

```sh
sudo eopkg install meson ninja gcc pkgconf libadwaita-devel libgtk-4-devel libjson-glib-devel glib2-devel gobject-introspection-devel gettext-devel
```

ffmpeg (opcijsko, samo če želiš dejansko pretvarjati medijske datoteke)

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

- Solus (example):

```sh
# refresh local repo metadata first
sudo eopkg update-repo
# then install development and runtime packages
sudo eopkg install -y meson ninja gcc libjson-glib-devel ffmpeg libgtk-4-devel libadwaita-devel
```

Notes for Solus:
- `pkg-config` is usually available on a developer system; if it's missing, install the relevant package from the repos.
- If the Meson in Solus repos is older than the project's `meson_version` requirement, install Meson via `pipx` or `pip3 --user` to get a newer version:

```sh
pipx install meson
# or
pip3 install --user meson
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
