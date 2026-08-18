#!/usr/bin/env python3
"""
baC - Orodje za urejanje MKV datotek
Avtor: BArko & SimOne

Uporaba:
  bac          - Zaženi GUI
  bac film.mkv - Zaženi GUI in odpri MKV datoteko
  bac -q       - Uredi MKV: en zvok in en prednostni podnapis
  bac -qq      - Kot -q, ampak zamenja izvorne datoteke po uspehu
"""

verzija = "v1.0.10"

import argparse
import importlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from pathlib import Path
from types import SimpleNamespace
from tkinter import filedialog, messagebox, ttk
from urllib.parse import unquote, urlparse


def normaliziraj_pot_argumenta(vrednost):
    """Pretvori navadno pot ali file:// URI iz .desktop zagona v lokalno pot."""
    pot = str(vrednost).strip()
    if pot.startswith("{") and pot.endswith("}"):
        pot = pot[1:-1]
    if pot.startswith("file://"):
        razclenjeno = urlparse(pot)
        pot = unquote(razclenjeno.path)
    else:
        pot = unquote(pot)
    return pot


def _uvozi_tkinterdnd2():
    """Vrne TkinterDnD razred, če je dodatna knjižnica na voljo."""
    try:
        from tkinterdnd2 import TkinterDnD

        return TkinterDnD
    except ImportError:
        return None


def _pripravi_tkinterdnd2():
    """Po potrebi ponudi namestitev podpore za povleci in spusti."""
    tkinter_dnd = _uvozi_tkinterdnd2()
    if tkinter_dnd is not None:
        return tkinter_dnd

    bootstrap = tk.Tk()
    bootstrap.withdraw()
    namesti = messagebox.askyesno(
        "Manjka podpora za povleci in spusti",
        "Za povleci in spusti manjka paket tkinterdnd2.\n\n"
        "Ali ga želi baC samodejno namestiti?",
        parent=bootstrap,
    )
    if not namesti:
        bootstrap.destroy()
        return None

    ukaz = [sys.executable, "-m", "pip", "install"]
    # V sistemskem Pythonu namesti paket za trenutnega uporabnika. V virtualnem
    # okolju --user ni dovoljen oziroma ni smiseln, zato uporabimo okolje samo.
    if getattr(sys, "prefix", sys.executable) == getattr(
        sys, "base_prefix", sys.prefix
    ):
        ukaz.append("--user")
    ukaz.append("tkinterdnd2>=0.4.4")

    try:
        rezultat = subprocess.run(
            ukaz,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as napaka:
        rezultat = None
        napaka_besedilo = str(napaka)
    else:
        napaka_besedilo = (rezultat.stderr or rezultat.stdout or "").strip()

    importlib.invalidate_caches()
    tkinter_dnd = _uvozi_tkinterdnd2()
    bootstrap.destroy()

    if rezultat is not None and rezultat.returncode == 0 and tkinter_dnd is not None:
        return tkinter_dnd

    sporocilo = "Namestitev paketa tkinterdnd2 ni uspela."
    if napaka_besedilo:
        sporocilo += f"\n\n{napaka_besedilo[:1200]}"
    messagebox.showwarning(
        "Povleci in spusti ni na voljo",
        sporocilo + "\n\nDatoteke lahko še vedno odpirate z gumbom 'Odpri MKV'.",
    )
    return None


class OperacijaPrekinjena(Exception):
    """Izjema za nadzorovano prekinitev operacije ob zapiranju GUI-ja."""


class ZaobljenGumb(tk.Canvas):
    """Lahek gumb s stabilnim 5 px zaobljenim ozadjem."""

    def __init__(self, master, text, command, paleta, poudarjen=False, **kwargs):
        kwargs.pop("style", None)
        self._besedilo = text
        self._ukaz = command
        self._paleta = paleta
        self._poudarjen = poudarjen
        self._stanje = "normal"
        self._pod_misko = False
        self._pritisnjen = False
        self._pisava = tkfont.Font(
            root=master,
            family="TkDefaultFont",
            size=10,
            weight="bold" if poudarjen else "normal",
        )
        sirina = max(76, self._pisava.measure(text) + 28)
        super().__init__(
            master,
            width=sirina,
            height=36,
            background=paleta["povrsina"],
            borderwidth=0,
            highlightthickness=0,
            relief="flat",
            takefocus=True,
            cursor="hand2",
            **kwargs,
        )
        self.bind("<Configure>", lambda _dogodek: self._narisi())
        self.bind("<Enter>", self._vstop)
        self.bind("<Leave>", self._izstop)
        self.bind("<ButtonPress-1>", self._pritisni)
        self.bind("<ButtonRelease-1>", self._spusti)
        self.bind("<Key-space>", self._tipka)
        self.bind("<Key-Return>", self._tipka)
        self._narisi()

    def _barve_gumba(self):
        if self._stanje == "disabled":
            return self._paleta["ozadje_okvir"], self._paleta["besedilo_umirjeno"]
        if self._pritisnjen or self._pod_misko:
            return self._paleta["gumb_aktivno"], self._paleta["besedilo"]
        return self._paleta["gumb_ozadje"], self._paleta["besedilo"]

    def _narisi_obliko(self, x1, y1, x2, y2, polmer, barva):
        self.create_rectangle(x1 + polmer, y1, x2 - polmer, y2, fill=barva, outline="")
        self.create_rectangle(x1, y1 + polmer, x2, y2 - polmer, fill=barva, outline="")
        self.create_oval(x1, y1, x1 + polmer * 2, y1 + polmer * 2, fill=barva, outline="")
        self.create_oval(x2 - polmer * 2, y1, x2, y1 + polmer * 2, fill=barva, outline="")
        self.create_oval(x1, y2 - polmer * 2, x1 + polmer * 2, y2, fill=barva, outline="")
        self.create_oval(x2 - polmer * 2, y2 - polmer * 2, x2, y2, fill=barva, outline="")

    def _narisi(self):
        self.delete("all")
        sirina = max(self.winfo_width(), 20)
        visina = max(self.winfo_height(), 20)
        ozadje, besedilo = self._barve_gumba()
        self._narisi_obliko(1, 1, sirina - 1, visina - 1, 5, ozadje)
        self.create_text(
            sirina / 2,
            visina / 2,
            text=self._besedilo,
            fill=besedilo,
            font=self._pisava,
        )

    def _vstop(self, _dogodek):
        self._pod_misko = True
        self._narisi()

    def _izstop(self, _dogodek):
        self._pod_misko = False
        self._pritisnjen = False
        self._narisi()

    def _pritisni(self, _dogodek):
        if self._stanje != "disabled":
            self.focus_set()
            self._pritisnjen = True
            self._narisi()
        return "break"

    def _spusti(self, _dogodek):
        naj_izvede = self._pritisnjen and self._stanje != "disabled"
        self._pritisnjen = False
        self._narisi()
        if naj_izvede and self._ukaz:
            self._ukaz()
        return "break"

    def _tipka(self, _dogodek):
        if self._stanje != "disabled" and self._ukaz:
            self._ukaz()
        return "break"

    def cget(self, option):
        if option == "state":
            return self._stanje
        if option == "text":
            return self._besedilo
        return super().cget(option)

    def configure(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)
        stanje = kwargs.pop("state", None)
        besedilo = kwargs.pop("text", None)
        ukaz = kwargs.pop("command", None)
        if stanje is not None:
            self._stanje = str(stanje)
        if besedilo is not None:
            self._besedilo = str(besedilo)
        if ukaz is not None:
            self._ukaz = ukaz
        rezultat = super().configure(**kwargs) if kwargs else None
        if stanje is not None or besedilo is not None:
            self._narisi()
        return rezultat

    config = configure


class BaMKV:
    def __init__(self, root, prisiljena_tema=None, zacetne_datoteke=None):
        self.root = root
        self.root.title(f"baC {verzija} - Urejanje MKV datotek")
        self.root.geometry("1200x800")
        self.root.minsize(800, 600)

        self.mkv_pot = None
        self.stevilke_sledi = []
        self.prisiljena_tema = prisiljena_tema
        self.zacetne_datoteke = zacetne_datoteke or []
        self._drag_drop_nastavljen = False
        self._drop_callback_po_widgetu = {}
        self._wayland_drop_funcid = None
        self._gui_zaklenjen = False
        self._stanja_widgetov = []
        self._stanja_zavihkov = []
        self._zaklenjen_zavihek = None
        self._zavihek_bind_id = None
        self._trenutni_proces = None
        self._zapiranje = False
        self._predpomnjena_mkv_pot = None
        self._predpomnjene_sledi = None
        self.root.protocol("WM_DELETE_WINDOW", self._zapri_aplikacijo)

        # Zaznaj temo in nastavi barve
        self._nastavi_temo()

        self._preveri_orodja()
        self._ustvari_vmesnik()
        self._nastavi_drag_drop()
        if self.zacetne_datoteke:
            self.root.after(100, self._odpri_zacetne_datoteke)

    def _zaznavaj_temo_namizja(self):
        """Zazna ali je sistem v temni ali svetli temi."""
        # Poskusi GNOME/GTK nastavitve
        try:
            rezultat = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if rezultat.returncode == 0:
                vrednost = rezultat.stdout.strip().lower()
                if "dark" in vrednost:
                    return "temna"
                elif "light" in vrednost or "default" in vrednost:
                    return "svetla"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Poskusi GTK tema
        try:
            rezultat = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if rezultat.returncode == 0:
                tema = rezultat.stdout.strip().lower()
                if "dark" in tema:
                    return "temna"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Poskusi KDE Plasma
        try:
            kde_conf = os.path.expanduser("~/.config/kdeglobals")
            if os.path.exists(kde_conf):
                with open(kde_conf, "r") as f:
                    vsebina = f.read().lower()
                    if "breeze-dark" in vsebina or "breezedark" in vsebina:
                        return "temna"
        except (IOError, PermissionError):
            pass

        # Poskusi xfconf za XFCE
        try:
            rezultat = subprocess.run(
                ["xfconf-query", "-c", "xsettings", "-p", "/Net/ThemeName"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if rezultat.returncode == 0:
                tema = rezultat.stdout.strip().lower()
                if "dark" in tema:
                    return "temna"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Privzeto svetla tema
        return "svetla"

    def _normaliziraj_barvo(self, vrednost):
        """Pretvori sistemsko Tk barvo v šestnajstiški zapis."""
        if not vrednost or str(vrednost).lower() in {"none", "null"}:
            return None
        try:
            rdeca, zelena, modra = self.root.winfo_rgb(str(vrednost))
        except tk.TclError:
            return None
        return f"#{rdeca // 256:02x}{zelena // 256:02x}{modra // 256:02x}"

    def _prilagodi_barvo(self, barva, cilj, delez):
        """Barvo rahlo približa ciljni barvi za hover/pressed stanje."""
        try:
            kanali = [int(barva[i : i + 2], 16) for i in (1, 3, 5)]
            ciljni = [int(cilj[i : i + 2], 16) for i in (1, 3, 5)]
        except (TypeError, ValueError):
            return barva
        novi = [round(a + (b - a) * delez) for a, b in zip(kanali, ciljni)]
        return "#" + "".join(f"{kanal:02x}" for kanal in novi)

    def _barva_sledi_temi(self, barva, tema):
        """Preveri, da prebrana sistemska barva ni v očitnem nasprotju s temo."""
        try:
            kanali = [int(barva[i : i + 2], 16) for i in (1, 3, 5)]
        except (TypeError, ValueError):
            return False
        svetlost = sum(kanali) / 3
        return svetlost < 160 if tema == "temna" else svetlost >= 160

    def _preberi_sistemske_barve_gumba(self):
        """Prebere osnovno in hover barvo gumba iz aktivne GTK teme."""
        try:
            import gi

            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk

            preverjanje = Gtk.init_check([])
            uspesno = preverjanje[0] if isinstance(preverjanje, tuple) else preverjanje
            if not uspesno:
                return None, None

            gumb = Gtk.Button(label=" ")
            kontekst = gumb.get_style_context()

            def v_hex(barva):
                if not barva or getattr(barva, "alpha", 0) < 0.05:
                    return None
                return "#{:02x}{:02x}{:02x}".format(
                    round(barva.red * 255),
                    round(barva.green * 255),
                    round(barva.blue * 255),
                )

            return (
                v_hex(kontekst.get_background_color(Gtk.StateFlags.NORMAL)),
                v_hex(kontekst.get_background_color(Gtk.StateFlags.PRELIGHT)),
            )
        except (ImportError, ValueError, RuntimeError, AttributeError):
            return None, None

    def _ustvari_gumb(self, master, text, command=None, style=None, **kwargs):
        """Ustvari gumb, ki je neodvisen od pravokotnega ttk rendererja."""
        return ZaobljenGumb(
            master,
            text=text,
            command=command,
            paleta=self.barve,
            poudarjen=style == "Accent.TButton",
            **kwargs,
        )

    def _nastavi_temo(self):
        """Nastavi barve glede na temo namizja."""
        if self.prisiljena_tema:
            tema = self.prisiljena_tema
        else:
            tema = self._zaznavaj_temo_namizja()
        self.tema = tema

        # Definiraj barvne sheme
        if tema == "temna":
            self.barve = {
                "ozadje": "#111827",
                "ozadje_okvir": "#1f2937",
                "povrsina": "#182231",
                "besedilo": "#e5e7eb",
                "besedilo_umirjeno": "#9ca3af",
                "poudarek": "#6d8cff",
                "poudarek_temno": "#4f6ed8",
                "gumb_ozadje": "#263244",
                "gumb_aktivno": "#334155",
                "vnos_ozadje": "#0f172a",
                "drevo_ozadje": "#151f2e",
                "drevo_izbrano": "#4568d6",
                "obroba": "#334155",
                "obroba_svetla": "#475569",
            }
        else:
            self.barve = {
                "ozadje": "#f3f6fb",
                "ozadje_okvir": "#ffffff",
                "povrsina": "#ffffff",
                "besedilo": "#172033",
                "besedilo_umirjeno": "#64748b",
                "poudarek": "#2563eb",
                "poudarek_temno": "#1d4ed8",
                "gumb_ozadje": "#e8eef7",
                "gumb_aktivno": "#dbe5f2",
                "vnos_ozadje": "#ffffff",
                "drevo_ozadje": "#ffffff",
                "drevo_izbrano": "#2563eb",
                "obroba": "#d5deeb",
                "obroba_svetla": "#e5ebf3",
            }

        # Pred preklopom na clam preberemo osnovno barvo gumba iz aktivne
        # namizne Tk teme. Tako barva sledi uporabnikovim nastavitvam.
        stil = ttk.Style()
        sistemska_barva_gumba, sistemska_aktivna_barva_gumba = (
            self._preberi_sistemske_barve_gumba()
        )
        if not sistemska_barva_gumba:
            sistemska_barva_gumba = self._normaliziraj_barvo(
                stil.lookup("TButton", "background")
                or self.root.option_get("background", "Button")
            )
        if not sistemska_aktivna_barva_gumba:
            sistemska_aktivna_barva_gumba = self._normaliziraj_barvo(
                stil.lookup("TButton", "background", state=("active",))
            )
        if (
            not self.prisiljena_tema
            and sistemska_barva_gumba
            and self._barva_sledi_temi(sistemska_barva_gumba, tema)
        ):
            self.barve["gumb_ozadje"] = sistemska_barva_gumba
            self.barve["gumb_aktivno"] = (
                sistemska_aktivna_barva_gumba
                or self._prilagodi_barvo(
                    sistemska_barva_gumba,
                    "#ffffff" if tema == "svetla" else "#000000",
                    0.12,
                )
            )

        # Poskusi uporabiti clam temo kot osnovo
        try:
            stil.theme_use("clam")
        except tk.TclError:
            pass

        # Nastavi barve za okno
        self.root.configure(bg=self.barve["ozadje"])

        # Nastavi globalne barve za standardne Tk widgete (dialogi, meniji, itd.)
        self.root.option_add("*Background", self.barve["ozadje"])
        self.root.option_add("*Foreground", self.barve["besedilo"])
        self.root.option_add("*selectBackground", self.barve["drevo_izbrano"])
        self.root.option_add("*selectForeground", "#ffffff")
        self.root.option_add("*Entry.Background", self.barve["vnos_ozadje"])
        self.root.option_add("*Entry.Foreground", self.barve["besedilo"])
        self.root.option_add("*Listbox.Background", self.barve["vnos_ozadje"])
        self.root.option_add("*Listbox.Foreground", self.barve["besedilo"])
        self.root.option_add("*Menu.Background", self.barve["ozadje"])
        self.root.option_add("*Menu.Foreground", self.barve["besedilo"])
        self.root.option_add("*Menu.activeBackground", self.barve["drevo_izbrano"])
        self.root.option_add("*Menu.activeForeground", "#ffffff")
        self.root.option_add("*Button.Background", self.barve["gumb_ozadje"])
        self.root.option_add("*Button.Foreground", self.barve["besedilo"])
        self.root.option_add("*Button.activeBackground", self.barve["gumb_aktivno"])
        self.root.option_add("*Button.activeForeground", self.barve["besedilo"])
        self.root.option_add("*Label.Background", self.barve["ozadje"])
        self.root.option_add("*Label.Foreground", self.barve["besedilo"])
        self.root.option_add("*Checkbutton.Background", self.barve["ozadje"])
        self.root.option_add("*Checkbutton.Foreground", self.barve["besedilo"])
        self.root.option_add("*Checkbutton.activeBackground", self.barve["ozadje"])
        self.root.option_add("*Checkbutton.activeForeground", self.barve["besedilo"])
        self.root.option_add("*Checkbutton.selectColor", self.barve["vnos_ozadje"])
        self.root.option_add("*Radiobutton.Background", self.barve["ozadje"])
        self.root.option_add("*Radiobutton.Foreground", self.barve["besedilo"])
        self.root.option_add("*Radiobutton.activeBackground", self.barve["ozadje"])
        self.root.option_add("*Radiobutton.activeForeground", self.barve["besedilo"])
        self.root.option_add("*Radiobutton.selectColor", self.barve["vnos_ozadje"])
        self.root.option_add("*Combobox.Background", self.barve["vnos_ozadje"])
        self.root.option_add("*Combobox.Foreground", self.barve["besedilo"])
        self.root.option_add("*TCombobox*Listbox.background", self.barve["vnos_ozadje"])
        self.root.option_add("*TCombobox*Listbox.foreground", self.barve["besedilo"])
        self.root.option_add(
            "*TCombobox*Listbox.selectBackground", self.barve["drevo_izbrano"]
        )
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

        # Nastavi stile za ttk widgete
        stil.configure(
            ".",
            background=self.barve["ozadje"],
            foreground=self.barve["besedilo"],
            fieldbackground=self.barve["vnos_ozadje"],
            troughcolor=self.barve["ozadje_okvir"],
            bordercolor=self.barve["obroba"],
            lightcolor=self.barve["obroba"],
            darkcolor=self.barve["obroba"],
        )

        stil.configure("TFrame", background=self.barve["povrsina"])
        stil.configure("Card.TFrame", background=self.barve["povrsina"])
        stil.configure("Header.TFrame", background=self.barve["ozadje"])
        stil.configure("Status.TFrame", background=self.barve["ozadje"])
        stil.configure(
            "TLabelframe",
            background=self.barve["povrsina"],
            bordercolor=self.barve["obroba"],
            lightcolor=self.barve["obroba"],
            darkcolor=self.barve["obroba"],
            relief="solid",
            borderwidth=1,
        )
        stil.configure(
            "TLabelframe.Label",
            background=self.barve["povrsina"],
            foreground=self.barve["besedilo"],
            font=("TkDefaultFont", 10, "bold"),
        )
        stil.configure(
            "Card.TLabelframe",
            background=self.barve["povrsina"],
            bordercolor=self.barve["obroba"],
            lightcolor=self.barve["obroba"],
            darkcolor=self.barve["obroba"],
            relief="solid",
            borderwidth=1,
        )
        stil.configure(
            "Card.TLabelframe.Label",
            background=self.barve["povrsina"],
            foreground=self.barve["besedilo"],
            font=("TkDefaultFont", 10, "bold"),
        )
        stil.configure(
            "TLabel", background=self.barve["povrsina"], foreground=self.barve["besedilo"]
        )
        stil.configure(
            "Title.TLabel",
            background=self.barve["ozadje"],
            foreground=self.barve["besedilo"],
            font=("TkDefaultFont", 18, "bold"),
        )
        stil.configure(
            "Subtitle.TLabel",
            background=self.barve["ozadje"],
            foreground=self.barve["besedilo_umirjeno"],
            font=("TkDefaultFont", 10),
        )
        stil.configure(
            "Section.TLabel",
            background=self.barve["povrsina"],
            foreground=self.barve["besedilo"],
            font=("TkDefaultFont", 10, "bold"),
        )
        stil.configure(
            "Hint.TLabel",
            background=self.barve["povrsina"],
            foreground=self.barve["besedilo_umirjeno"],
            font=("TkDefaultFont", 9),
        )
        stil.configure(
            "Status.TLabel",
            background=self.barve["ozadje"],
            foreground=self.barve["besedilo_umirjeno"],
            padding=(4, 3),
        )
        stil.configure(
            "Napredek.TLabel",
            background=self.barve["ozadje_okvir"],
            foreground=self.barve["besedilo"],
        )
        stil.configure(
            "TButton",
            background=self.barve["gumb_ozadje"],
            foreground=self.barve["besedilo"],
            bordercolor=self.barve["obroba"],
            lightcolor=self.barve["obroba_svetla"],
            darkcolor=self.barve["obroba"],
            padding=[12, 7],
        )
        stil.map(
            "TButton",
            background=[
                ("active", self.barve["gumb_aktivno"]),
                ("pressed", self.barve["poudarek"]),
            ],
        )
        stil.configure(
            "Accent.TButton",
            background=self.barve["poudarek"],
            foreground="#ffffff",
            bordercolor=self.barve["poudarek"],
            lightcolor=self.barve["poudarek"],
            darkcolor=self.barve["poudarek_temno"],
            padding=[14, 8],
            font=("TkDefaultFont", 10, "bold"),
        )
        stil.map(
            "Accent.TButton",
            background=[
                ("disabled", self.barve["gumb_ozadje"]),
                ("active", self.barve["poudarek_temno"]),
                ("pressed", self.barve["poudarek_temno"]),
            ],
            foreground=[("disabled", self.barve["besedilo_umirjeno"]), ("!disabled", "#ffffff")],
        )
        stil.configure(
            "Quiet.TButton",
            background=self.barve["povrsina"],
            foreground=self.barve["poudarek"],
            bordercolor=self.barve["obroba"],
            lightcolor=self.barve["obroba"],
            darkcolor=self.barve["obroba"],
            padding=[12, 7],
        )
        stil.map("Quiet.TButton", background=[("active", self.barve["gumb_aktivno"])])
        stil.configure(
            "TEntry",
            fieldbackground=self.barve["vnos_ozadje"],
            foreground=self.barve["besedilo"],
            bordercolor=self.barve["obroba"],
            lightcolor=self.barve["obroba"],
            darkcolor=self.barve["obroba"],
            padding=[8, 6],
        )
        stil.configure(
            "TCombobox",
            fieldbackground=self.barve["vnos_ozadje"],
            foreground=self.barve["besedilo"],
            bordercolor=self.barve["obroba"],
            lightcolor=self.barve["obroba"],
            darkcolor=self.barve["obroba"],
        )
        stil.configure(
            "TCheckbutton",
            background=self.barve["povrsina"],
            foreground=self.barve["besedilo"],
        )
        stil.map(
            "TCheckbutton",
            background=[("active", self.barve["povrsina"])],
            foreground=[("active", self.barve["besedilo"])],
        )
        stil.configure(
            "TRadiobutton",
            background=self.barve["povrsina"],
            foreground=self.barve["besedilo"],
        )
        stil.map(
            "TRadiobutton",
            background=[("active", self.barve["povrsina"])],
            foreground=[("active", self.barve["besedilo"])],
        )
        stil.configure(
            "TNotebook",
            background=self.barve["ozadje"],
            bordercolor=self.barve["obroba"],
            lightcolor=self.barve["obroba"],
            darkcolor=self.barve["obroba"],
            tabmargins=[0, 6, 0, 0],
            padding=0,
        )
        stil.configure(
            "TNotebook.Tab",
            background=self.barve["gumb_ozadje"],
            foreground=self.barve["besedilo"],
            padding=[12, 8],
            bordercolor=self.barve["obroba"],
            lightcolor=self.barve["obroba"],
            darkcolor=self.barve["obroba"],
            focuscolor=self.barve["obroba"],
        )
        stil.map(
            "TNotebook.Tab",
            background=[
                ("selected", self.barve["gumb_aktivno"]),
                ("active", self.barve["gumb_aktivno"]),
            ],
            foreground=[
                ("selected", self.barve["besedilo"]),
                ("active", self.barve["besedilo"]),
            ],
            lightcolor=[("selected", self.barve["obroba"])],
            darkcolor=[("selected", self.barve["obroba"])],
            bordercolor=[("selected", self.barve["obroba"])],
        )

        # Treeview
        stil.configure(
            "Treeview",
            background=self.barve["drevo_ozadje"],
            foreground=self.barve["besedilo"],
            fieldbackground=self.barve["drevo_ozadje"],
            bordercolor=self.barve["obroba"],
            borderwidth=0,
            relief="flat",
            rowheight=30,
        )
        stil.configure(
            "Treeview.Heading",
            background=self.barve["ozadje_okvir"],
            foreground=self.barve["besedilo"],
            bordercolor=self.barve["obroba"],
            relief="flat",
            padding=[10, 8],
            font=("TkDefaultFont", 9, "bold"),
        )
        stil.map(
            "Treeview.Heading",
            background=[("active", self.barve["gumb_aktivno"])],
            foreground=[("active", self.barve["besedilo"])],
        )
        stil.map(
            "Treeview",
            background=[("selected", self.barve["drevo_izbrano"])],
            foreground=[("selected", "#ffffff")],
        )

        # Progressbar
        stil.configure(
            "TProgressbar",
            background=self.barve["poudarek"],
            troughcolor=self.barve["ozadje_okvir"],
        )

        # Scrollbar
        stil.configure(
            "TScrollbar",
            background=self.barve["gumb_ozadje"],
            troughcolor=self.barve["ozadje_okvir"],
            bordercolor=self.barve["obroba"],
            arrowcolor=self.barve["besedilo"],
        )
        stil.map(
            "TScrollbar",
            background=[("active", self.barve["gumb_aktivno"])],
            arrowcolor=[("active", self.barve["besedilo"])],
        )

        print(f"Tema namizja: {tema}")

    def _odpri_dialog_datoteka(
        self, naslov="Izberi datoteko", tipi=None, zacetna_mapa=None
    ):
        """Odpre dialog za izbiro datoteke z uporabo sistemskega dialoga."""
        # Poskusi zenity (GNOME/GTK)
        if shutil.which("zenity"):
            cmd = ["zenity", "--file-selection", f"--title={naslov}"]
            if tipi:
                for opis, vzorci in tipi:
                    if vzorci != "*.*":
                        for vzorec in vzorci.split():
                            cmd.append(f"--file-filter={opis} | {vzorec}")
                cmd.append("--file-filter=Vse datoteke | *")
            if zacetna_mapa:
                cmd.append(f"--filename={zacetna_mapa}/")
            try:
                rezultat = subprocess.run(cmd, capture_output=True, text=True)
                if rezultat.returncode == 0:
                    return rezultat.stdout.strip()
                return None
            except Exception:
                pass

        # Poskusi kdialog (KDE)
        if shutil.which("kdialog"):
            cmd = ["kdialog", "--getopenfilename"]
            if zacetna_mapa:
                cmd.append(zacetna_mapa)
            else:
                cmd.append(os.getcwd())
            if tipi:
                filtri = []
                for opis, vzorci in tipi:
                    if vzorci != "*.*":
                        filtri.append(f"{vzorci}|{opis}")
                if filtri:
                    cmd.append(" ".join(filtri))
            cmd.extend(["--title", naslov])
            try:
                rezultat = subprocess.run(cmd, capture_output=True, text=True)
                if rezultat.returncode == 0:
                    return rezultat.stdout.strip()
                return None
            except Exception:
                pass

        # Nazaj na tkinter
        filetypes = []
        if tipi:
            for opis, vzorci in tipi:
                filetypes.append((opis, vzorci))
        return filedialog.askopenfilename(
            title=naslov,
            filetypes=filetypes or [("Vse datoteke", "*.*")],
            initialdir=zacetna_mapa,
        )

    def _shrani_dialog_datoteka(
        self, naslov="Shrani datoteko", privzeto_ime=None, tipi=None, zacetna_mapa=None
    ):
        """Odpre dialog za shranjevanje datoteke z uporabo sistemskega dialoga."""
        # Poskusi zenity (GNOME/GTK)
        if shutil.which("zenity"):
            cmd = ["zenity", "--file-selection", "--save", f"--title={naslov}"]
            if privzeto_ime:
                if zacetna_mapa:
                    cmd.append(f"--filename={os.path.join(zacetna_mapa, privzeto_ime)}")
                else:
                    cmd.append(f"--filename={privzeto_ime}")
            elif zacetna_mapa:
                cmd.append(f"--filename={zacetna_mapa}/")
            if tipi:
                for opis, vzorci in tipi:
                    if vzorci != "*.*":
                        for vzorec in vzorci.split():
                            cmd.append(f"--file-filter={opis} | {vzorec}")
                cmd.append("--file-filter=Vse datoteke | *")
            cmd.append("--confirm-overwrite")
            try:
                rezultat = subprocess.run(cmd, capture_output=True, text=True)
                if rezultat.returncode == 0:
                    return rezultat.stdout.strip()
                return None
            except Exception:
                pass

        # Poskusi kdialog (KDE)
        if shutil.which("kdialog"):
            cmd = ["kdialog", "--getsavefilename"]
            if zacetna_mapa and privzeto_ime:
                cmd.append(os.path.join(zacetna_mapa, privzeto_ime))
            elif zacetna_mapa:
                cmd.append(zacetna_mapa)
            elif privzeto_ime:
                cmd.append(privzeto_ime)
            else:
                cmd.append(os.getcwd())
            if tipi:
                filtri = []
                for opis, vzorci in tipi:
                    if vzorci != "*.*":
                        filtri.append(f"{vzorci}|{opis}")
                if filtri:
                    cmd.append(" ".join(filtri))
            cmd.extend(["--title", naslov])
            try:
                rezultat = subprocess.run(cmd, capture_output=True, text=True)
                if rezultat.returncode == 0:
                    return rezultat.stdout.strip()
                return None
            except Exception:
                pass

        # Nazaj na tkinter
        filetypes = []
        if tipi:
            for opis, vzorci in tipi:
                filetypes.append((opis, vzorci))
        return filedialog.asksaveasfilename(
            title=naslov,
            initialfile=privzeto_ime,
            filetypes=filetypes or [("Vse datoteke", "*.*")],
            initialdir=zacetna_mapa,
        )

    def _ustvari_dialog(self, naslov, sirina=300, visina=120):
        """Ustvari dialog s pravilno barvo ozadja."""
        dialog = tk.Toplevel(self.root)
        dialog.title(naslov)
        dialog.geometry(f"{sirina}x{visina}")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=self.barve["ozadje"])
        return dialog

    def _nastavi_drag_drop(self):
        """Nastavi povleci in spusti za celotno aplikacijo."""
        # Zagotovi, da je okno v celoti realizirano pred registracijo DnD tarč
        self.root.update_idletasks()
        self._registriraj_drag_drop()

    def _drop_tarce(self):
        """Vrne widgete, ki sprejemajo povlečene datoteke."""
        return [
            (self.root, self._drop_mkv),
            (self.okvir_datoteka, self._drop_mkv),
            (self.vnos_pot, self._drop_mkv),
            (self.gumb_odpri_mkv, self._drop_mkv),
            (self.vnos_podnapis, self._drop_podnapis),
            (self.vnos_hitro_video, self._drop_hitro_video),
            (self.drevo_vhod, self._drop_vhodne),
            (self.gumb_podnapisi, self._drop_op_podnapisi),
            (self.gumb_zvok, self._drop_op_zvok),
        ]

    def _sprejmi_drop(self, dogodek=None):
        """Potrdi DnD akcijo pred dejanskim spustom."""
        return "copy"

    def _izvedi_drop(self, callback, dogodek):
        callback(dogodek)
        return "copy"

    def _wayland_cached_drop(self, widget_path, podatki, x_root, y_root):
        """Fallback za Wayland/XWayland, ko tkdnd izgubi selection ob prvem dropu."""
        callback = self._drop_callback_po_widgetu.get(widget_path)
        widget = None

        try:
            widget = self.root.nametowidget(widget_path)
        except KeyError:
            widget = self.root

        while callback is None and widget is not self.root:
            try:
                widget = widget.nametowidget(widget.winfo_parent())
            except KeyError:
                widget = self.root
            callback = self._drop_callback_po_widgetu.get(getattr(widget, "_w", "."))

        if callback is None:
            return "refuse_drop"

        dogodek = SimpleNamespace(
            action="copy",
            actions=("copy", "move", "link", "ask", "private"),
            data=podatki,
            name="<<Drop>>",
            type="text/uri-list",
            types=("text/uri-list",),
            widget=widget,
            x_root=int(x_root),
            y_root=int(y_root),
        )
        return self._izvedi_drop(callback, dogodek)

    def _registriraj_drag_drop_tarco(self, widget, callback, tip_datotek):
        widget.drop_target_register(tip_datotek)
        widget.dnd_bind("<<DropEnter>>", self._sprejmi_drop)
        widget.dnd_bind("<<DropPosition>>", self._sprejmi_drop)
        widget.dnd_bind(
            "<<Drop>>",
            lambda dogodek, cb=callback: self._izvedi_drop(cb, dogodek),
        )

    def _popravi_wayland_prvi_drop(self):
        """Na Wayland/XWayland inicializira XDND tarčo tudi brez prvega Position eventa."""
        if (
            self.root.tk.call("tk", "windowingsystem") != "x11"
            or not os.environ.get("WAYLAND_DISPLAY")
        ):
            return

        if self._wayland_drop_funcid is None:
            self._wayland_drop_funcid = self.root.register(self._wayland_cached_drop)

        self.root.tk.eval(
            r"""
            if {[namespace exists ::tkdnd::xdnd]
                && [llength [info commands ::tkdnd::xdnd::HandleXdndDrop]]
                && ![info exists ::tkdnd::xdnd::_bac_first_drop_patch]} {
                set ::tkdnd::xdnd::_bac_first_drop_patch 1
                rename ::tkdnd::xdnd::HandleXdndDrop ::tkdnd::xdnd::HandleXdndDrop_bac_orig

                proc ::tkdnd::xdnd::HandleXdndDrop { time } {
                    set current_target [::tkdnd::generic::GetDropTarget]

                    if {[string length $current_target]} {
                        catch {::tkdnd::generic::GetDroppedData $time} cached_data
                    }

                    if {![string length $current_target]} {
                        if {![catch {winfo pointerxy .} xy] && [llength $xy] == 2} {
                            set rootX [lindex $xy 0]
                            set rootY [lindex $xy 1]
                            set containing [winfo containing -displayof . $rootX $rootY]

                            if {[string length $containing]} {
                                catch {
                                    foreach {drop_target common_source common_target} \
                                        [::tkdnd::generic::FindWindowWithCommonTypes \
                                            $containing $::tkdnd::generic::_typelist] {
                                            break
                                        }

                                    if {[string length $drop_target] && [llength $common_source]} {
                                        set ::tkdnd::generic::_drop_target $drop_target
                                        set ::tkdnd::generic::_common_drag_source_types $common_source
                                        set ::tkdnd::generic::_common_drop_target_types $common_target
                                        set ::tkdnd::generic::_last_mouse_root_x $rootX
                                        set ::tkdnd::generic::_last_mouse_root_y $rootY
                                        set ::tkdnd::generic::_action copy
                                    }
                                }
                            }
                        }
                    }

                    if {[catch {
                        set pressedkeys [::tkdnd::xdnd::GetPressedKeys [::tkdnd::generic::GetDropTarget]]
                    }]} {
                        set pressedkeys {}
                    }

                    set source [::tkdnd::generic::GetDragSource]
                    set target [::tkdnd::generic::GetDropTarget]
                    if {[string length $target]} {
                        catch {
                            foreach {resolved_target common_source common_target} \
                                [::tkdnd::generic::FindWindowWithCommonTypes \
                                    $target $::tkdnd::generic::_typelist] {
                                    break
                                }

                            if {[string length $resolved_target] && [llength $common_source]} {
                                set target $resolved_target
                                set ::tkdnd::generic::_drop_target $resolved_target
                                set ::tkdnd::generic::_common_drag_source_types $common_source
                                set ::tkdnd::generic::_common_drop_target_types $common_target
                                set ::tkdnd::generic::_action copy
                            }
                        }
                    }
                    set common_types [::tkdnd::generic::GetDragSourceCommonTypes]

                    if {![catch {
                        ::tkdnd::xdnd::GetDroppedData $source $target $common_types $time
                    } fresh_data]} {
                        ::tkdnd::generic::SetDroppedData $fresh_data
                        set cached_data $fresh_data
                    } elseif {[info exists cached_data] && [string length $cached_data]} {
                        ::tkdnd::generic::SetDroppedData $cached_data
                    }

                    set rootX $::tkdnd::generic::_last_mouse_root_x
                    set rootY $::tkdnd::generic::_last_mouse_root_y
                    if {![string length $rootX] || ![string length $rootY]} {
                        if {![catch {winfo pointerxy .} xy] && [llength $xy] == 2} {
                            set rootX [lindex $xy 0]
                            set rootY [lindex $xy 1]
                        } else {
                            set rootX 0
                            set rootY 0
                        }
                    }

                    set code [catch {
                        ::tkdnd::generic::HandleDrop {} {} $pressedkeys $rootX $rootY $time
                    } result options]

                    if {$code} {
                        return -options $options $result
                    }

                    if {$result eq "refuse_drop"
                        && [info exists ::tkdnd::xdnd::_bac_cached_drop_cmd]
                        && [info exists cached_data]
                        && [string length $cached_data]
                        && [string length $target]} {
                        return [uplevel #0 [list \
                            $::tkdnd::xdnd::_bac_cached_drop_cmd \
                            $target \
                            $cached_data \
                            $rootX \
                            $rootY \
                        ]]
                    }
                    return $result
                }
            }
            """
        )
        self.root.tk.call(
            "set", "::tkdnd::xdnd::_bac_cached_drop_cmd", self._wayland_drop_funcid
        )

    def _registriraj_drag_drop(self):
        """Registrira DnD tarče, ko Tk že obdela začetni izris."""
        if self._drag_drop_nastavljen:
            return
        try:
            # Poskusi uvoziti tkinterdnd2
            from tkinterdnd2 import DND_FILES

            self._drop_callback_po_widgetu = {
                widget._w: callback for widget, callback in self._drop_tarce()
            }
            self._popravi_wayland_prvi_drop()

            for widget, callback in self._drop_tarce():
                self._registriraj_drag_drop_tarco(widget, callback, DND_FILES)

            self._drag_drop_nastavljen = True

        except ImportError:
            # tkinterdnd2 ni na voljo - uporabi alternativno metodo za Linux
            self._nastavi_xdnd()

    def _nastavi_xdnd(self):
        """Alternativna metoda za povleci in spusti brez tkinterdnd2."""
        # Poskusi nativno Tk DnD podporo
        try:
            self.root.tk.call("package", "require", "tkdnd")
            self._drop_callback_po_widgetu = {
                widget._w: callback for widget, callback in self._drop_tarce()
            }
            self._popravi_wayland_prvi_drop()

            for widget, callback in self._drop_tarce():
                self.root.tk.call(
                    "tkdnd::drop_target", "register", widget._w, "DND_Files"
                )
                self.root.tk.call("bind", widget._w, "<<DropEnter>>", "list copy")
                self.root.tk.call("bind", widget._w, "<<DropPosition>>", "list copy")
                funcid = self.root.register(
                    lambda podatki, cb=callback: self._izvedi_drop(
                        cb, SimpleNamespace(data=podatki, action="copy")
                    )
                )
                self.root.tk.call("bind", widget._w, "<<Drop>>", f"{funcid} %D")
            self._drag_drop_nastavljen = True
        except tk.TclError:
            print("Povleci in spusti ni na voljo. Namestite tkdnd ali tkinterdnd2.")

    def _parsiraj_drop_pot(self, podatki):
        """Parsira pot iz dogodka povleci in spusti."""
        pot = normaliziraj_pot_argumenta(podatki)
        # Vzemi prvo datoteko če jih je več
        if "\n" in pot:
            pot = pot.split("\n")[0].strip()
        return pot

    def _nalozi_mkv(self, pot):
        """Odpre MKV datoteko v glavnem pogledu."""
        self.mkv_pot = pot
        self.vnos_pot.delete(0, tk.END)
        self.vnos_pot.insert(0, pot)
        self._osvezi_sledi()
        self._osvezi_odstranitev()
        self.zavihki.select(self.zavihek_pregled)
        self.status.config(text=f"Odprto: {Path(pot).name}")

    def _nalozi_hitro_video(self, pot):
        """Naloži video v zavihek za hitro pretvorbo."""
        self.vnos_hitro_video.delete(0, tk.END)
        self.vnos_hitro_video.insert(0, pot)
        self._poisci_povezane_hitro(pot)
        self.zavihki.select(self.zavihek_hitro)
        self.status.config(text=f"Video za hitro pretvorbo: {Path(pot).name}")

    def _odpri_zacetne_datoteke(self):
        """Obdela datoteke, podane ob zagonu programa."""
        for vrednost in self.zacetne_datoteke:
            pot = normaliziraj_pot_argumenta(vrednost)
            if not pot or not os.path.isfile(pot):
                continue

            koncnica = Path(pot).suffix.lower()
            if koncnica == ".mkv":
                self._nalozi_mkv(pot)
                return

            messagebox.showwarning("Opozorilo", "Izberite MKV datoteko.")
            return

        self.status.config(text="Zagonska datoteka ni bila najdena.")

    def _drop_mkv(self, dogodek):
        """Obdelaj povlečeno in spuščeno MKV datoteko."""
        pot = self._parsiraj_drop_pot(dogodek.data)
        if pot and os.path.isfile(pot):
            koncnica = Path(pot).suffix.lower()
            if koncnica == ".mkv":
                self._nalozi_mkv(pot)
            else:
                messagebox.showwarning("Opozorilo", "Izberite MKV datoteko.")
        return dogodek.action if hasattr(dogodek, "action") else None

    def _drop_podnapis(self, dogodek):
        """Obdelaj povlečeno datoteko podnapisov."""
        pot = self._parsiraj_drop_pot(dogodek.data)
        if pot and os.path.isfile(pot):
            koncnica = Path(pot).suffix.lower()
            if koncnica in [".srt", ".ass", ".ssa", ".sub", ".txt", ".vtt"]:
                self.vnos_podnapis.delete(0, tk.END)
                self.vnos_podnapis.insert(0, pot)
            else:
                messagebox.showwarning("Opozorilo", "Izberite datoteko podnapisov.")
        return dogodek.action if hasattr(dogodek, "action") else None

    def _drop_hitro_video(self, dogodek):
        """Obdelaj povlečeno video datoteko za hitro pretvorbo."""
        pot = self._parsiraj_drop_pot(dogodek.data)
        if pot and os.path.isfile(pot):
            koncnica = Path(pot).suffix.lower()
            video_koncnice = [
                ".mp4",
                ".avi",
                ".mov",
                ".wmv",
                ".flv",
                ".webm",
                ".m4v",
                ".mpeg",
                ".mpg",
                ".mkv",
            ]
            if koncnica in video_koncnice:
                self._nalozi_hitro_video(pot)
            else:
                messagebox.showwarning("Opozorilo", "Izberite video datoteko.")
        return dogodek.action if hasattr(dogodek, "action") else None

    def _poisci_povezane_hitro(self, pot):
        """Poišče povezane datoteke za hitro pretvorbo."""
        # Počisti prejšnje
        for vrstica in self.drevo_hitro.get_children():
            self.drevo_hitro.delete(vrstica)
        self.hitro_datoteke.clear()
        self.hitro_izbrane.clear()

        # Poišči povezane datoteke
        mapa = os.path.dirname(pot)
        osnovni_ime = Path(pot).stem

        koncnice_sub = [".srt", ".ass", ".ssa", ".sub", ".vtt", ".txt"]
        koncnice_audio = [
            ".mp3",
            ".aac",
            ".ac3",
            ".flac",
            ".ogg",
            ".wav",
            ".m4a",
            ".opus",
            ".dts",
        ]

        najdene = []

        for datoteka in os.listdir(mapa):
            dat_pot = os.path.join(mapa, datoteka)
            if not os.path.isfile(dat_pot) or dat_pot == pot:
                continue

            dat_stem = Path(datoteka).stem
            dat_suffix = Path(datoteka).suffix.lower()

            if (
                dat_stem == osnovni_ime
                or dat_stem.startswith(osnovni_ime + ".")
                or dat_stem.startswith(osnovni_ime + "_")
            ):
                if dat_suffix in koncnice_sub:
                    najdene.append(
                        {"vrsta": "Podnapisi", "pot": dat_pot, "ime": datoteka}
                    )
                elif dat_suffix in koncnice_audio:
                    najdene.append({"vrsta": "Zvok", "pot": dat_pot, "ime": datoteka})

        # Dodaj video
        self.hitro_datoteke.append(
            {"vrsta": "Video", "pot": pot, "ime": Path(pot).name}
        )
        self.hitro_izbrane.add("0")
        self.drevo_hitro.insert(
            "", "end", iid="0", values=("☑", "Video", Path(pot).name)
        )

        # Dodaj najdene
        for i, dat in enumerate(najdene, start=1):
            self.hitro_datoteke.append(dat)
            self.hitro_izbrane.add(str(i))
            self.drevo_hitro.insert(
                "", "end", iid=str(i), values=("☑", dat["vrsta"], dat["ime"])
            )

        stevilo_sub = sum(1 for d in najdene if d["vrsta"] == "Podnapisi")
        self.status.config(
            text=f"Najdenih {len(najdene)} povezanih datotek ({stevilo_sub} podnapisov)"
        )

    def _drop_vhodne(self, dogodek):
        """Obdelaj povlečene datoteke v seznam vhodnih datotek."""
        pot = self._parsiraj_drop_pot(dogodek.data)
        if pot and os.path.isfile(pot):
            koncnica = Path(pot).suffix.lower()

            # Določi vrsto datoteke
            video_koncnice = [
                ".mp4",
                ".avi",
                ".mkv",
                ".mov",
                ".wmv",
                ".flv",
                ".webm",
                ".m4v",
                ".mpeg",
                ".mpg",
            ]
            audio_koncnice = [
                ".mp3",
                ".aac",
                ".ac3",
                ".flac",
                ".ogg",
                ".wav",
                ".m4a",
                ".opus",
                ".dts",
                ".eac3",
            ]
            sub_koncnice = [".srt", ".ass", ".ssa", ".sub", ".txt", ".vtt"]

            if koncnica in video_koncnice:
                vrsta = "video"
            elif koncnica in audio_koncnice:
                vrsta = "audio"
            elif koncnica in sub_koncnice:
                vrsta = "podnapisi"
            else:
                messagebox.showwarning("Opozorilo", "Nepodprta vrsta datoteke.")
                return dogodek.action if hasattr(dogodek, "action") else None

            # Vprašaj za jezik
            jezik = self._vprasaj_jezik()

            self.vhodne_datoteke.append({"vrsta": vrsta, "pot": pot, "jezik": jezik})
            self.drevo_vhod.insert(
                "",
                "end",
                values=(
                    vrsta.capitalize() if vrsta != "audio" else "Zvok",
                    Path(pot).name,
                    jezik,
                ),
            )
        return dogodek.action if hasattr(dogodek, "action") else None

    def _drop_op_podnapisi(self, dogodek):
        """Obdelaj povlečene podnapise na gumbu - doda operacijo."""
        pot = self._parsiraj_drop_pot(dogodek.data)
        if pot and os.path.isfile(pot):
            koncnica = Path(pot).suffix.lower()
            if koncnica not in [".srt", ".ass", ".ssa", ".sub", ".vtt", ".txt"]:
                messagebox.showwarning("Opozorilo", "Izberite datoteko podnapisov.")
                return dogodek.action if hasattr(dogodek, "action") else None

            if not self.mkv_pot:
                messagebox.showwarning("Opozorilo", "Najprej odprite MKV datoteko.")
                return dogodek.action if hasattr(dogodek, "action") else None

            # Dialog za nastavitve
            self._prikazi_dialog_podnapisi(pot)
        return dogodek.action if hasattr(dogodek, "action") else None

    def _drop_op_zvok(self, dogodek):
        """Obdelaj povlečeno zvočno datoteko na gumbu - doda operacijo."""
        pot = self._parsiraj_drop_pot(dogodek.data)
        if pot and os.path.isfile(pot):
            koncnica = Path(pot).suffix.lower()
            audio_koncnice = [
                ".mp3",
                ".aac",
                ".ac3",
                ".flac",
                ".ogg",
                ".wav",
                ".m4a",
                ".opus",
                ".dts",
                ".eac3",
            ]
            if koncnica not in audio_koncnice:
                messagebox.showwarning("Opozorilo", "Izberite zvočno datoteko.")
                return dogodek.action if hasattr(dogodek, "action") else None

            if not self.mkv_pot:
                messagebox.showwarning("Opozorilo", "Najprej odprite MKV datoteko.")
                return dogodek.action if hasattr(dogodek, "action") else None

            jezik = self._vprasaj_jezik()
            self._dodaj_operacijo(
                "Dodaj zvok",
                f"{Path(pot).name} ({jezik})",
                {"pot": pot, "jezik": jezik},
            )
        return dogodek.action if hasattr(dogodek, "action") else None

    def _prikazi_dialog_podnapisi(self, pot):
        """Prikaže dialog za nastavitve podnapisov."""
        dialog = self._ustvari_dialog("Nastavitve podnapisov", 350, 230)

        ttk.Label(dialog, text="Jezik:").pack(pady=(10, 5))
        jezik_izbira = ttk.Combobox(
            dialog,
            values=[
                "slv - Slovenščina",
                "eng - Angleščina",
                "hrv - Hrvaščina",
                "und - Nedoločen",
            ],
            width=25,
        )
        jezik_izbira.set("slv - Slovenščina")
        jezik_izbira.pack(pady=5)

        privzet_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(dialog, text="Nastavi kot privzet", variable=privzet_var).pack(
            pady=5
        )

        zamenjaj_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            dialog, text="Zamenjaj vse obstoječe podnapise", variable=zamenjaj_var
        ).pack(pady=5)

        def potrdi():
            jezik = jezik_izbira.get().split(" - ")[0]
            self._dodaj_operacijo(
                "Dodaj podnapise",
                f"{Path(pot).name} ({jezik})",
                {
                    "pot": pot,
                    "jezik": jezik,
                    "privzet": privzet_var.get(),
                    "zamenjaj": zamenjaj_var.get(),
                },
            )
            dialog.destroy()

        self._ustvari_gumb(dialog, text="Potrdi", command=potrdi).pack(pady=10)

    def _nastavi_zasedeno(self, sporocilo):
        """Nastavi aplikacijo v zaseden način s sporočilom."""
        if not self._gui_zaklenjen:
            self._zakleni_gui()
        self.status.config(text=sporocilo)
        self.napredek.pack(side="right", padx=(10, 0))
        self.napredek.start(10)
        self.root.config(cursor="watch")
        self.root.update_idletasks()

    def _nastavi_prosto(self, sporocilo="Pripravljeno"):
        """Nastavi aplikacijo nazaj v prosto stanje."""
        self.napredek.stop()
        self.napredek.pack_forget()
        if hasattr(self, "okvir_napredek_operacij"):
            self.napredek_operacij.stop()
            self.napredek_operacij.configure(mode="determinate")
            self.okvir_napredek_operacij.pack_forget()
        if hasattr(self, "gumb_izvedi"):
            self.gumb_izvedi.config(state="normal")
        self.root.config(cursor="")
        self.status.config(text=sporocilo)
        if self._zapiranje:
            # Zapiranje odložimo do izhoda iz trenutnega callbacka; sicer bi
            # root.destroy() znotraj GUI callbacka prekinil tekoči ukaz.
            self.root.after(50, self.root.destroy)
            return
        self._odkleni_gui()
        self.root.update_idletasks()

    def _sprehodi_widgete(self, widget):
        """Vrne vse podrejene widgete, tudi v ugnezdenih okvirjih."""
        for otrok in widget.winfo_children():
            yield otrok
            yield from self._sprehodi_widgete(otrok)

    def _zakleni_gui(self):
        """Onemogoči vse interaktivne kontrole, medtem ko operacija teče."""
        self._gui_zaklenjen = True
        self._stanja_widgetov = []
        self._stanja_zavihkov = []
        if hasattr(self, "zavihki"):
            self._zaklenjen_zavihek = self.zavihki.index("current")
            for indeks in range(self.zavihki.index("end")):
                stanje = self.zavihki.tab(indeks, "state")
                self._stanja_zavihkov.append((indeks, stanje))
                if indeks != self._zaklenjen_zavihek:
                    self.zavihki.tab(indeks, state="disabled")
            self._zavihek_bind_id = self.zavihki.bind(
                "<Button-1>", self._blokiraj_klike_zavihkov, add="+"
            )
        try:
            self.meni_sledi.unpost()
        except (AttributeError, tk.TclError):
            pass

        for widget in self._sprehodi_widgete(self.root):
            # Indikatorji niso interaktivni in morajo ostati vizualno aktivni.
            if (
                isinstance(widget, ttk.Progressbar)
                or widget is getattr(self, "opis_napredka_operacij", None)
                or widget is getattr(self, "zavihki", None)
            ):
                continue
            try:
                stanje = widget.cget("state")
            except (tk.TclError, AttributeError):
                continue
            if stanje != "disabled":
                try:
                    widget.configure(state="disabled")
                    self._stanja_widgetov.append((widget, stanje))
                except tk.TclError:
                    pass

    def _odkleni_gui(self):
        """Obnovi stanja kontrol po koncu operacije."""
        if hasattr(self, "zavihki"):
            if self._zavihek_bind_id:
                self.zavihki.unbind("<Button-1>", self._zavihek_bind_id)
                self._zavihek_bind_id = None
            for indeks, stanje in self._stanja_zavihkov:
                try:
                    self.zavihki.tab(indeks, state=stanje)
                except tk.TclError:
                    pass
        self._stanja_zavihkov = []
        self._zaklenjen_zavihek = None
        for widget, stanje in self._stanja_widgetov:
            try:
                widget.configure(state=stanje)
            except tk.TclError:
                pass
        self._stanja_widgetov = []
        self._gui_zaklenjen = False

    def _blokiraj_klike_zavihkov(self, _dogodek):
        """Med operacijo prepreči menjavo zavihka, tudi na trenutnem zavihku."""
        return "break"

    def _ubij_trenutni_proces(self):
        """Ustavi trenutni ukaz skupaj z morebitnimi podprocesi."""
        proces = self._trenutni_proces
        if proces is None or proces.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(proces.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            proces.terminate()

    def _zapri_aplikacijo(self):
        """Zapre GUI; med operacijo pred tem zahteva potrditev prekinitve."""
        if not self._gui_zaklenjen:
            self.root.destroy()
            return

        if not messagebox.askyesno(
            "Prekini operacijo?",
            "Operacija še teče. Ali jo želite prekiniti in zapreti aplikacijo?",
            parent=self.root,
        ):
            return

        self._zapiranje = True
        self._ubij_trenutni_proces()

    def _nastavi_napredek_operacij(self, vrednost, sporocilo):
        """Prikaže napredek ali nedoločen indikator za dolgotrajno fazo."""
        if not hasattr(self, "okvir_napredek_operacij"):
            return
        self.napredek_operacij.stop()
        if vrednost is None:
            self.napredek_operacij.configure(mode="indeterminate")
            self.opis_napredka_operacij.config(text=sporocilo)
            self.napredek_operacij.start(10)
        else:
            self.napredek_operacij.configure(mode="determinate")
            self.napredek_operacij_var.set(vrednost)
            self.opis_napredka_operacij.config(
                text=f"{sporocilo} ({int(vrednost)} %)"
            )
        self.okvir_napredek_operacij.pack(
            fill="x", pady=(5, 0), before=self.drevo_operacije
        )
        self.root.update_idletasks()

    def _izvedi_ukaz_z_osvezevanjem(self, ukaz):
        """Izvede zunanji ukaz in vmes omogoči osveževanje prikaza napredka."""
        # Začasni datoteki preprečita blokado procesa, do katere pride, če se
        # PIPE napolni z izhodom ffmpeg/mkvmerge, medtem ko GUI čaka.
        try:
            with tempfile.TemporaryFile() as stdout_dat:
                with tempfile.TemporaryFile() as stderr_dat:
                    povratna_koda, stdout, stderr = (
                        self._izvedi_proces_z_datotekama(
                            ukaz, stdout_dat, stderr_dat
                        )
                    )
        except OSError as e:
            # Tudi napake zagona (npr. izbrisano orodje ali nedostopna mapa)
            # pretvorimo v obliko, ki jo vsi GUI postopki že obravnavajo.
            raise subprocess.CalledProcessError(
                e.errno or 1,
                ukaz,
                stderr=str(e).encode(errors="replace"),
            ) from e

        if self._zapiranje:
            raise OperacijaPrekinjena()
        if povratna_koda:
            raise subprocess.CalledProcessError(
                povratna_koda, ukaz, output=stdout, stderr=stderr
            )
        return stdout, stderr

    def _izvedi_proces_z_datotekama(self, ukaz, stdout_dat, stderr_dat):
        """Izvede proces z izhodom v datotekah, ki se ne moreta napolniti."""
        rezultat = {}
        koncano = threading.Event()

        def izvajaj():
            proces = None
            try:
                proces = subprocess.Popen(
                    ukaz,
                    stdout=stdout_dat,
                    stderr=stderr_dat,
                    start_new_session=True,
                )
                self._trenutni_proces = proces
                if self._zapiranje:
                    self._ubij_trenutni_proces()

                while proces.poll() is None:
                    if self._zapiranje:
                        self._ubij_trenutni_proces()
                        break
                    time.sleep(0.05)

                if self._zapiranje:
                    try:
                        proces.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(os.getpgid(proces.pid), signal.SIGKILL)
                        except (ProcessLookupError, PermissionError, OSError):
                            proces.kill()
                        proces.wait()
                else:
                    proces.wait()

                stdout_dat.seek(0)
                stderr_dat.seek(0)
                rezultat["povratna_koda"] = proces.returncode
                rezultat["stdout"] = stdout_dat.read()
                rezultat["stderr"] = stderr_dat.read()
            except BaseException as napaka:
                rezultat["napaka"] = napaka
            finally:
                self._trenutni_proces = None
                koncano.set()

        nit = threading.Thread(target=izvajaj, daemon=True)
        nit.start()

        # Tkinter ostane odziven, vendar ne uporabljamo nevarnega root.update(),
        # ki lahko ponovno vstopi v poljubne GUI callbacke.
        signal_koncano = tk.BooleanVar(self.root, value=False)

        def preveri_konec():
            if koncano.is_set():
                signal_koncano.set(True)
            else:
                self.root.after(50, preveri_konec)

        self.root.after(0, preveri_konec)
        self.root.wait_variable(signal_koncano)
        nit.join()

        if "napaka" in rezultat:
            raise rezultat["napaka"]
        return (
            rezultat["povratna_koda"],
            rezultat["stdout"],
            rezultat["stderr"],
        )

    @staticmethod
    def _opis_napake_procesa(napaka):
        """Varno pretvori stderr procesa ali izjemo v besedilo za uporabnika."""
        stderr = getattr(napaka, "stderr", None)
        if isinstance(stderr, bytes):
            return stderr.decode(errors="replace")
        if stderr:
            return str(stderr)
        return str(napaka)

    @staticmethod
    def _nova_zacasna_mkv_pot(ciljna_pot, oznaka):
        """Vrne enolično prosto pot za začasno MKV ob ciljni datoteki."""
        cilj = Path(ciljna_pot)
        fd, pot = tempfile.mkstemp(
            prefix=f".{cilj.stem}_{oznaka}_",
            suffix=".mkv",
            dir=str(cilj.parent),
        )
        os.close(fd)
        os.remove(pot)
        return pot

    @staticmethod
    def _varno_odstrani(pot):
        """Odstrani začasno datoteko, če obstaja, brez prekrivanja prvotne napake."""
        if not pot:
            return
        try:
            os.remove(pot)
        except OSError:
            pass

    def _preveri_zapisljivost_cilja(self, ciljna_pot):
        """Preveri, ali lahko cilj ustvarimo oziroma prepišemo."""
        cilj = Path(ciljna_pot).expanduser()
        mapa = cilj.parent
        try:
            if not mapa.is_dir():
                raise OSError(f"Ciljna mapa ne obstaja: {mapa}")
            if hasattr(os, "ST_RDONLY") and os.statvfs(mapa).f_flag & os.ST_RDONLY:
                raise OSError(f"Ciljna mapa je samo za branje: {mapa}")
            if not os.access(mapa, os.W_OK | os.X_OK):
                raise OSError(f"V ciljni mapi ni dovoljenja za pisanje: {mapa}")
            if cilj.exists() and not os.access(cilj, os.W_OK):
                raise OSError(f"V ciljno datoteko ni dovoljenja za pisanje: {cilj}")
        except OSError as napaka:
            messagebox.showerror(
                "Cilj ni zapisljiv",
                f"Datoteke ni mogoče shraniti.\n\n{napaka}\n\n"
                "Izberite drugo mapo ali odklopite USB pravilno, da bo zapisljiv.",
            )
            return False

        if cilj.exists() and not messagebox.askyesno(
            "Prepiši datoteko?",
            f"Datoteka že obstaja:\n\n{cilj}\n\nJo želite prepisati?",
        ):
            return False
        return True

    def _poisci_orodje(self, ime):
        """Poišče orodje v sistemu, vključno s flatpak paketi."""
        # Najprej preveri sistemsko pot
        pot = shutil.which(ime)
        if pot:
            return pot

        # Poišči v flatpak aplikacijah
        try:
            rezultat = subprocess.run(
                ["flatpak", "list", "--app", "--columns=application"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if rezultat.returncode == 0:
                aplikacije = rezultat.stdout.strip().split("\n")

                # FFmpeg flatpak
                if ime in ["ffmpeg", "ffprobe"]:
                    for app in aplikacije:
                        if "ffmpeg" in app.lower():
                            return f"flatpak run --command={ime} {app}"

                # MKVToolNix flatpak
                if ime == "mkvmerge":
                    for app in aplikacije:
                        if "mkvtoolnix" in app.lower():
                            return f"flatpak run --command=mkvmerge {app}"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Preveri pogoste lokacije
        pogoste_poti = [
            f"/usr/bin/{ime}",
            f"/usr/local/bin/{ime}",
            f"/snap/bin/{ime}",
            os.path.expanduser(f"~/bin/{ime}"),
            os.path.expanduser(f"~/.local/bin/{ime}"),
        ]

        for pot in pogoste_poti:
            if os.path.isfile(pot) and os.access(pot, os.X_OK):
                return pot

        return None

    def _preveri_orodja(self):
        """Preveri, ali so potrebna orodja nameščena."""
        self.ffmpeg = self._poisci_orodje("ffmpeg")
        self.ffprobe = self._poisci_orodje("ffprobe")
        self.mkvmerge = self._poisci_orodje("mkvmerge")

        manjkajoca = []
        if not self.ffmpeg:
            manjkajoca.append("ffmpeg")
        if not self.ffprobe:
            manjkajoca.append("ffprobe")
        if not self.mkvmerge:
            manjkajoca.append("mkvmerge (mkvtoolnix)")

        if manjkajoca:
            messagebox.showwarning(
                "Manjkajoča orodja",
                f"Manjkajo naslednja orodja: {', '.join(manjkajoca)}\n\n"
                "Namestite jih za polno funkcionalnost:\n"
                "• APT: sudo apt install ffmpeg mkvtoolnix\n"
                "• Flatpak: flatpak install org.ffmpeg.FFmpeg\n"
                "• Snap: sudo snap install ffmpeg",
            )
        else:
            # Prikaži najdena orodja v konzoli
            print(f"Najdena orodja:")
            print(f"  ffmpeg: {self.ffmpeg}")
            print(f"  ffprobe: {self.ffprobe}")
            print(f"  mkvmerge: {self.mkvmerge}")

    def _ustvari_vmesnik(self):
        """Ustvari glavni vmesnik."""
        # Glava aplikacije
        okvir_glava = ttk.Frame(self.root, style="Header.TFrame")
        okvir_glava.pack(fill="x", padx=18, pady=(14, 8))
        ttk.Label(okvir_glava, text="baC", style="Title.TLabel").pack(side="left")
        ttk.Label(
            okvir_glava,
            text="  urejanje in združevanje MKV datotek",
            style="Subtitle.TLabel",
        ).pack(side="left", pady=(6, 0))

        # Zgornja kartica za izbiro datoteke
        self.okvir_datoteka = ttk.Frame(self.root, style="Card.TFrame", padding=12)
        self.okvir_datoteka.pack(fill="x", padx=18, pady=(0, 8))

        okvir_napis = ttk.Frame(self.okvir_datoteka, style="Card.TFrame")
        okvir_napis.pack(fill="x", pady=(0, 8))
        ttk.Label(
            okvir_napis, text="Vhodna MKV datoteka", style="Section.TLabel"
        ).pack(side="left")
        ttk.Label(
            okvir_napis,
            text="Izberite datoteko ali jo povlecite v okno",
            style="Hint.TLabel",
        ).pack(side="right")

        okvir_vnos = ttk.Frame(self.okvir_datoteka, style="Card.TFrame")
        okvir_vnos.pack(fill="x")
        self.vnos_pot = ttk.Entry(okvir_vnos, width=70)
        self.vnos_pot.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.gumb_odpri_mkv = self._ustvari_gumb(
            okvir_vnos,
            text="Odpri MKV",
            command=self._odpri_mkv,
            style="Accent.TButton",
        )
        self.gumb_odpri_mkv.pack(side="left")

        # Zavihki
        self.zavihki = ttk.Notebook(self.root)
        self.zavihki.pack(fill="both", expand=True, padx=18, pady=(0, 8))

        # Zavihek: Pregled sledi
        self.zavihek_pregled = ttk.Frame(self.zavihki, padding=10)
        self.zavihki.add(self.zavihek_pregled, text="Pregled sledi")
        self._ustvari_pregled(self.zavihek_pregled)

        # Zavihek: Dodaj podnapise
        okvir_podnapisi = ttk.Frame(self.zavihki, padding=10)
        self.zavihki.add(okvir_podnapisi, text="Dodaj podnapise")
        self._ustvari_podnapisi(okvir_podnapisi)

        # Zavihek: Pretvori
        okvir_pretvorba = ttk.Frame(self.zavihki, padding=10)
        self.zavihki.add(okvir_pretvorba, text="Pretvori")
        self._ustvari_pretvorbo(okvir_pretvorba)

        # Zavihek: Odstrani sledi
        okvir_odstrani = ttk.Frame(self.zavihki, padding=10)
        self.zavihki.add(okvir_odstrani, text="Odstrani sledi")
        self._ustvari_odstranitev(okvir_odstrani)

        # Zavihek: Ustvari MKV
        okvir_ustvari = ttk.Frame(self.zavihki, padding=10)
        self.zavihki.add(okvir_ustvari, text="Ustvari MKV")
        self._ustvari_izdelavo(okvir_ustvari)

        # Zavihek: Hitro pretvori v MKV
        self.zavihek_hitro = ttk.Frame(self.zavihki, padding=10)
        self.zavihki.add(self.zavihek_hitro, text="Hitro v MKV")
        self._ustvari_hitro_pretvorbo(self.zavihek_hitro)

        # Zavihek: Navodila
        okvir_navodila = ttk.Frame(self.zavihki, padding=10)
        self.zavihki.add(okvir_navodila, text="Navodila")
        self._ustvari_navodila(okvir_navodila)

        # Statusna vrstica
        okvir_status = ttk.Frame(self.root, style="Status.TFrame")
        okvir_status.pack(fill="x", padx=18, pady=(0, 12))

        self.status = ttk.Label(
            okvir_status,
            text="Pripravljeno",
            style="Status.TLabel",
            anchor="w",
        )
        self.status.pack(side="left", fill="x", expand=True)

        self.napredek = ttk.Progressbar(okvir_status, mode="indeterminate", length=150)
        self.napredek.pack(side="right", padx=(10, 0))
        self.napredek.pack_forget()  # Skrij na začetku

    def _ustvari_pregled(self, okvir):
        """Ustvari zavihek za pregled sledi z vrsto operacij."""
        # Zgornji del - pregled sledi
        okvir_sledi = ttk.LabelFrame(okvir, text="Sledi v datoteki", padding=5)
        okvir_sledi.pack(fill="both", expand=True)

        okvir_drevo = ttk.Frame(okvir_sledi)
        okvir_drevo.pack(fill="both", expand=True)

        stolpci = ("Št.", "Vrsta", "Kodek", "Jezik", "Naslov")
        self.drevo_sledi = ttk.Treeview(
            okvir_drevo, columns=stolpci, show="headings", height=5
        )

        for stolpec in stolpci:
            self.drevo_sledi.heading(stolpec, text=stolpec)
            self.drevo_sledi.column(stolpec, width=120)

        self.drevo_sledi.column("Št.", width=50)
        self.drevo_sledi.column("Vrsta", width=80)
        self.drevo_sledi.column("Kodek", width=150)
        self.drevo_sledi.column("Jezik", width=80)
        self.drevo_sledi.column("Naslov", width=200)

        drsnik = ttk.Scrollbar(
            okvir_drevo, orient="vertical", command=self.drevo_sledi.yview
        )
        self.drevo_sledi.configure(yscrollcommand=drsnik.set)

        self.drevo_sledi.pack(side="left", fill="both", expand=True)
        drsnik.pack(side="right", fill="y")

        # Kontekstni meni
        self.meni_sledi = tk.Menu(self.root, tearoff=0)
        self.meni_sledi.add_command(
            label="Odstrani sled", command=self._op_odstrani_sled
        )
        self.meni_sledi.add_command(
            label="Spremeni jezik", command=self._op_spremeni_jezik
        )
        self.meni_sledi.add_command(
            label="Spremeni naslov", command=self._op_spremeni_naslov
        )
        self.meni_sledi.add_command(
            label="Nastavi kot privzeto", command=self._op_nastavi_privzeto
        )
        self.meni_sledi.add_separator()
        self.meni_sledi.add_command(
            label="Pretvori zvok v AAC", command=lambda: self._op_pretvori_zvok("aac")
        )
        self.meni_sledi.add_command(
            label="Pretvori zvok v AC3", command=lambda: self._op_pretvori_zvok("ac3")
        )
        self.meni_sledi.add_command(
            label="Pretvori zvok v MP3", command=lambda: self._op_pretvori_zvok("mp3")
        )
        self.meni_sledi.add_separator()
        self.meni_sledi.add_command(
            label="Pretvori video v H.264 / AVC",
            command=lambda: self._op_pretvori_video("h264"),
        )
        self.meni_sledi.add_command(
            label="Pretvori video v H.265 / HEVC",
            command=lambda: self._op_pretvori_video("hevc"),
        )
        self.meni_sledi.add_command(
            label="Pretvori video v VP9",
            command=lambda: self._op_pretvori_video("vp9"),
        )

        self.drevo_sledi.bind("<Button-3>", self._prikazi_meni_sledi)
        self.root.bind_all("<Button-1>", self._zapri_meni_sledi, add="+")
        self.root.bind_all("<Escape>", self._zapri_meni_sledi, add="+")

        # Gumbi za dodajanje datotek
        okvir_dodaj = ttk.Frame(okvir_sledi)
        okvir_dodaj.pack(fill="x", pady=5)

        self._ustvari_gumb(
            okvir_dodaj,
            text="Osveži",
            command=lambda: self._osvezi_sledi(prisilno=True),
        ).pack(side="left", padx=2)
        self.gumb_podnapisi = self._ustvari_gumb(
            okvir_dodaj, text="+ Podnapisi", command=self._op_dodaj_podnapise
        )
        self.gumb_podnapisi.pack(side="left", padx=2)
        self.gumb_zvok = self._ustvari_gumb(
            okvir_dodaj, text="+ Zvok", command=self._op_dodaj_zvok
        )
        self.gumb_zvok.pack(side="left", padx=2)

        # Spodnji del - čakajoče operacije
        okvir_operacije = ttk.LabelFrame(okvir, text="Čakajoče operacije", padding=5)
        okvir_operacije.pack(fill="both", expand=True, pady=(5, 0))

        self.cakalne_operacije = []

        stolpci_op = ("Št.", "Operacija", "Podrobnosti")
        self.drevo_operacije = ttk.Treeview(
            okvir_operacije, columns=stolpci_op, show="headings", height=4
        )

        self.drevo_operacije.heading("Št.", text="#")
        self.drevo_operacije.heading("Operacija", text="Operacija")
        self.drevo_operacije.heading("Podrobnosti", text="Podrobnosti")

        self.drevo_operacije.column("Št.", width=40)
        self.drevo_operacije.column("Operacija", width=150)
        self.drevo_operacije.column("Podrobnosti", width=400)

        self.drevo_operacije.pack(fill="both", expand=True)

        # Gumbi za operacije
        okvir_gumbi = ttk.Frame(okvir_operacije)
        okvir_gumbi.pack(fill="x", pady=5)

        self._ustvari_gumb(
            okvir_gumbi, text="Odstrani izbrano", command=self._odstrani_operacijo
        ).pack(side="left", padx=2)
        self._ustvari_gumb(
            okvir_gumbi, text="Počisti vse", command=self._pocisti_operacije
        ).pack(side="left", padx=2)

        self.okvir_napredek_operacij = ttk.Frame(okvir_operacije)
        self.opis_napredka_operacij = ttk.Label(
            self.okvir_napredek_operacij,
            text="Pripravljam...",
            style="Napredek.TLabel",
        )
        self.opis_napredka_operacij.pack(anchor="w")
        self.napredek_operacij_var = tk.DoubleVar(value=0)
        self.napredek_operacij = ttk.Progressbar(
            self.okvir_napredek_operacij,
            variable=self.napredek_operacij_var,
            maximum=100,
            mode="determinate",
        )
        self.napredek_operacij.pack(fill="x", pady=(3, 0))

        self.gumb_izvedi = self._ustvari_gumb(
            okvir_gumbi,
            text="▶ Izvedi vse",
            command=self._izvedi_operacije,
            style="Accent.TButton",
        )
        self.gumb_izvedi.pack(side="right", padx=2, ipadx=10)

    def _prikazi_meni_sledi(self, dogodek):
        """Prikaže kontekstni meni za izbrano sled."""
        if self._gui_zaklenjen:
            self._zapri_meni_sledi()
            return "break"
        self.meni_sledi.unpost()
        vrstica = self.drevo_sledi.identify_row(dogodek.y)
        if vrstica:
            self.drevo_sledi.selection_set(vrstica)
            self.meni_sledi.post(dogodek.x_root, dogodek.y_root)

    def _zapri_meni_sledi(self, dogodek=None):
        """Zapre popup meni sledi ob kliku zunaj njega ali s tipko Escape."""
        if dogodek is not None and str(dogodek.widget).startswith(
            str(self.meni_sledi)
        ):
            return
        self.meni_sledi.unpost()

    def _pridobi_izbrano_sled(self):
        """Vrne podatke o izbrani sledi."""
        izbrana = self.drevo_sledi.selection()
        if not izbrana:
            return None
        vrednosti = self.drevo_sledi.item(izbrana[0], "values")
        return {
            "stevilka": vrednosti[0],
            "vrsta": vrednosti[1],
            "kodek": vrednosti[2],
            "jezik": vrednosti[3],
            "naslov": vrednosti[4],
        }

    def _dodaj_operacijo(self, tip, podrobnosti, podatki=None):
        """Doda operacijo v čakalno vrsto."""
        stevilka = len(self.cakalne_operacije) + 1
        operacija = {"tip": tip, "podrobnosti": podrobnosti, "podatki": podatki or {}}
        self.cakalne_operacije.append(operacija)
        self.drevo_operacije.insert("", "end", values=(stevilka, tip, podrobnosti))
        self.status.config(text=f"Dodana operacija: {tip}")

    def _osvezi_seznam_operacij(self):
        """Osveži prikaz seznama operacij."""
        for vrstica in self.drevo_operacije.get_children():
            self.drevo_operacije.delete(vrstica)
        for i, op in enumerate(self.cakalne_operacije, 1):
            self.drevo_operacije.insert(
                "", "end", values=(i, op["tip"], op["podrobnosti"])
            )

    def _odstrani_operacijo(self):
        """Odstrani izbrano operacijo iz čakalne vrste."""
        izbrana = self.drevo_operacije.selection()
        if izbrana:
            indeks = self.drevo_operacije.index(izbrana[0])
            if indeks < len(self.cakalne_operacije):
                del self.cakalne_operacije[indeks]
            self._osvezi_seznam_operacij()

    def _pocisti_operacije(self):
        """Počisti vse čakajoče operacije."""
        self.cakalne_operacije.clear()
        for vrstica in self.drevo_operacije.get_children():
            self.drevo_operacije.delete(vrstica)
        self.status.config(text="Operacije počiščene")

    def _op_odstrani_sled(self):
        """Doda operacijo za odstranitev sledi."""
        sled = self._pridobi_izbrano_sled()
        if sled:
            self._dodaj_operacijo(
                "Odstrani sled",
                f"Sled {sled['stevilka']}: {sled['vrsta']} ({sled['kodek']})",
                {"stevilka": sled["stevilka"]},
            )

    def _op_spremeni_jezik(self):
        """Doda operacijo za spremembo jezika."""
        sled = self._pridobi_izbrano_sled()
        if not sled:
            return

        dialog = self._ustvari_dialog("Spremeni jezik", 300, 120)

        ttk.Label(dialog, text="Nov jezik:").pack(pady=10)
        izbira = ttk.Combobox(
            dialog,
            values=[
                "slv - Slovenščina",
                "eng - Angleščina",
                "hrv - Hrvaščina",
                "srp - Srbščina",
                "deu - Nemščina",
                "ita - Italijanščina",
                "und - Nedoločen",
            ],
            width=25,
        )
        izbira.set("slv - Slovenščina")
        izbira.pack(pady=5)

        def potrdi():
            jezik = izbira.get().split(" - ")[0]
            self._dodaj_operacijo(
                "Spremeni jezik",
                f"Sled {sled['stevilka']}: {jezik}",
                {"stevilka": sled["stevilka"], "jezik": jezik},
            )
            dialog.destroy()

        self._ustvari_gumb(dialog, text="Potrdi", command=potrdi).pack(pady=10)

    def _op_spremeni_naslov(self):
        """Doda operacijo za spremembo naslova."""
        sled = self._pridobi_izbrano_sled()
        if not sled:
            return

        dialog = self._ustvari_dialog("Spremeni naslov", 350, 120)

        ttk.Label(dialog, text="Nov naslov:").pack(pady=10)
        vnos = ttk.Entry(dialog, width=40)
        vnos.insert(0, sled["naslov"])
        vnos.pack(pady=5)

        def potrdi():
            naslov = vnos.get()
            self._dodaj_operacijo(
                "Spremeni naslov",
                f'Sled {sled["stevilka"]}: "{naslov}"',
                {"stevilka": sled["stevilka"], "naslov": naslov},
            )
            dialog.destroy()

        self._ustvari_gumb(dialog, text="Potrdi", command=potrdi).pack(pady=10)

    def _op_nastavi_privzeto(self):
        """Doda operacijo za nastavitev privzete sledi."""
        sled = self._pridobi_izbrano_sled()
        if sled:
            self._dodaj_operacijo(
                "Nastavi privzeto",
                f"Sled {sled['stevilka']}: {sled['vrsta']}",
                {"stevilka": sled["stevilka"], "vrsta": sled["vrsta"]},
            )

    def _op_pretvori_zvok(self, kodek):
        """Doda operacijo za pretvorbo zvoka."""
        sled = self._pridobi_izbrano_sled()
        if not sled:
            return
        if sled["vrsta"] != "Zvok":
            messagebox.showwarning("Opozorilo", "Izberite zvočno sled.")
            return
        self._dodaj_operacijo(
            "Pretvori zvok",
            f"Sled {sled['stevilka']}: {sled['kodek']} → {kodek.upper()}",
            {"stevilka": sled["stevilka"], "kodek": kodek},
        )

    def _op_pretvori_video(self, kodek):
        """Doda operacijo za pretvorbo izbrane video sledi."""
        sled = self._pridobi_izbrano_sled()
        if not sled:
            return
        if sled["vrsta"] != "Video":
            messagebox.showwarning("Opozorilo", "Izberite video sled.")
            return

        imena = {"h264": "H.264 / AVC", "hevc": "H.265 / HEVC", "vp9": "VP9"}
        self._dodaj_operacijo(
            "Pretvori video",
            f"Sled {sled['stevilka']}: {sled['kodek']} → {imena[kodek]}",
            {"stevilka": sled["stevilka"], "kodek": kodek},
        )

    def _op_dodaj_podnapise(self):
        """Doda operacijo za dodajanje podnapisov."""
        if not self.mkv_pot:
            messagebox.showwarning("Opozorilo", "Najprej odprite MKV datoteko.")
            return

        pot = self._odpri_dialog_datoteka(
            naslov="Izberi datoteko podnapisov",
            tipi=[("Podnapisi", "*.srt *.ass *.ssa *.sub *.vtt")],
        )
        if not pot:
            return

        self._prikazi_dialog_podnapisi(pot)

    def _op_dodaj_zvok(self):
        """Doda operacijo za dodajanje zvočne sledi."""
        if not self.mkv_pot:
            messagebox.showwarning("Opozorilo", "Najprej odprite MKV datoteko.")
            return

        pot = self._odpri_dialog_datoteka(
            naslov="Izberi zvočno datoteko",
            tipi=[
                ("Zvočne datoteke", "*.mp3 *.aac *.ac3 *.flac *.ogg *.wav *.m4a *.opus")
            ],
        )
        if not pot:
            return

        jezik = self._vprasaj_jezik()
        self._dodaj_operacijo(
            "Dodaj zvok", f"{Path(pot).name} ({jezik})", {"pot": pot, "jezik": jezik}
        )

    def _izvedi_operacije(self):
        """Izvede vse čakajoče operacije."""
        if not self.mkv_pot:
            messagebox.showwarning("Opozorilo", "Najprej odprite MKV datoteko.")
            return

        if not self.cakalne_operacije:
            messagebox.showwarning("Opozorilo", "Ni čakajočih operacij.")
            return

        if not self.mkvmerge:
            messagebox.showerror("Napaka", "mkvmerge ni nameščen.")
            return

        if any(
            op["tip"] in ("Pretvori zvok", "Pretvori video")
            for op in self.cakalne_operacije
        ) and not self.ffmpeg:
            messagebox.showerror(
                "Napaka",
                "Za pretvorbo sledi potrebujete nameščen ffmpeg.",
            )
            return

        # Ciljna datoteka
        osnovni_dir = os.path.dirname(self.mkv_pot)
        osnovni_ime = Path(self.mkv_pot).stem
        ciljna_pot = self._shrani_dialog_datoteka(
            naslov="Shrani kot",
            zacetna_mapa=osnovni_dir,
            privzeto_ime=f"_{osnovni_ime}.mkv",
            tipi=[("MKV datoteke", "*.mkv")],
        )

        if not ciljna_pot:
            return

        if not ciljna_pot.endswith(".mkv"):
            ciljna_pot += ".mkv"

        if not self._preveri_zapisljivost_cilja(ciljna_pot):
            return

        self.gumb_izvedi.config(state="disabled")
        self._nastavi_zasedeno("Izvajam operacije...")
        self._nastavi_napredek_operacij(None, "Pripravljam operacije …")
        zacasna_pot = None
        izhodna_zacasna_pot = None

        try:
            # Zberi podatke za mkvmerge
            sledi_za_odstranitev = set()
            spremembe_jezika = {}
            spremembe_naslova = {}
            privzete_sledi = {"video": None, "audio": None, "subtitle": None}
            pretvorbe_zvoka = {}
            pretvorbe_videa = {}
            dodatne_datoteke = []

            for op in self.cakalne_operacije:
                tip = op["tip"]
                podatki = op["podatki"]

                if tip == "Odstrani sled":
                    sledi_za_odstranitev.add(str(podatki["stevilka"]))
                elif tip == "Spremeni jezik":
                    spremembe_jezika[str(podatki["stevilka"])] = podatki["jezik"]
                elif tip == "Spremeni naslov":
                    spremembe_naslova[str(podatki["stevilka"])] = podatki["naslov"]
                elif tip == "Nastavi privzeto":
                    vrsta = podatki["vrsta"].lower()
                    if vrsta == "zvok":
                        vrsta = "audio"
                    elif vrsta == "podnapisi":
                        vrsta = "subtitle"
                    privzete_sledi[vrsta] = str(podatki["stevilka"])
                elif tip == "Pretvori zvok":
                    pretvorbe_zvoka[str(podatki["stevilka"])] = podatki["kodek"]
                elif tip == "Pretvori video":
                    pretvorbe_videa[str(podatki["stevilka"])] = podatki["kodek"]
                elif tip == "Dodaj podnapise":
                    dodatne_datoteke.append({"vrsta": "subtitle", **podatki})
                elif tip == "Dodaj zvok":
                    dodatne_datoteke.append({"vrsta": "audio", **podatki})

            zamenjaj_vse_podnapise = any(
                op["tip"] == "Dodaj podnapise" and op["podatki"].get("zamenjaj")
                for op in self.cakalne_operacije
            )
            samo_pretvorbe = all(
                op["tip"] in ("Pretvori zvok", "Pretvori video")
                for op in self.cakalne_operacije
            )

            potrebujejo_track_id = bool(
                sledi_za_odstranitev
                or spremembe_jezika
                or spremembe_naslova
                or any(privzete_sledi.values())
            )
            mkv_track_map = {}
            if potrebujejo_track_id:
                mkv_track_map = self._pridobi_mkvmerge_track_map(
                    self.mkv_pot, self._pridobi_informacije()
                )
                if not mkv_track_map:
                    raise RuntimeError(
                        "Ni mogoče zanesljivo preslikati track ID-jev za mkvmerge."
                    )

            def mkv_track_id(ffprobe_id):
                try:
                    return mkv_track_map[str(ffprobe_id)]
                except KeyError as napaka:
                    raise RuntimeError(
                        f"Sledi {ffprobe_id} ni mogoče najti v mkvmerge."
                    ) from napaka

            # Če je potrebna pretvorba zvoka, najprej uporabi ffmpeg
            vhodna_datoteka = self.mkv_pot

            if (pretvorbe_zvoka or pretvorbe_videa) and self.ffmpeg:
                self._nastavi_zasedeno("Pretvarjam izbrane sledi...")
                self._nastavi_napredek_operacij(None, "Pretvarjam izbrane sledi …")
                if samo_pretvorbe:
                    izhodna_zacasna_pot = self._nova_zacasna_mkv_pot(
                        ciljna_pot, "output"
                    )
                    izhod_pretvorbe = izhodna_zacasna_pot
                else:
                    zacasna_pot = self._nova_zacasna_mkv_pot(
                        ciljna_pot, "temp_tracks"
                    )
                    izhod_pretvorbe = zacasna_pot

                if "flatpak run" in self.ffmpeg:
                    ukaz_ff = self.ffmpeg.split() + ["-i", self.mkv_pot, "-y"]
                else:
                    ukaz_ff = [self.ffmpeg, "-i", self.mkv_pot, "-y"]

                # Kopiraj vse sledi, pretvori le označene
                ukaz_ff.extend(["-map", "0", "-c", "copy"])

                for stevilka, kodek in pretvorbe_zvoka.items():
                    kodeki_map = {"aac": "aac", "ac3": "ac3", "mp3": "libmp3lame"}
                    ukaz_ff.extend([f"-c:{stevilka}", kodeki_map.get(kodek, "ac3")])
                    if kodek != "flac":
                        ukaz_ff.extend([f"-b:{stevilka}", "192k"])

                kodeki_videa = {
                    "h264": "libx264",
                    "hevc": "libx265",
                    "vp9": "libvpx-vp9",
                }
                for stevilka, kodek in pretvorbe_videa.items():
                    ukaz_ff.extend(
                        [f"-c:{stevilka}", kodeki_videa.get(kodek, "libx264"), "-crf", "23"]
                    )

                ukaz_ff.append(izhod_pretvorbe)
                self._izvedi_ukaz_z_osvezevanjem(ukaz_ff)
                vhodna_datoteka = izhod_pretvorbe

                # Če seznam vsebuje samo pretvorbe, je rezultat ffmpeg že
                # končni MKV. Drugi celoten prepis z mkvmerge ni potreben.
                if samo_pretvorbe:
                    os.replace(izhodna_zacasna_pot, ciljna_pot)
                    izhodna_zacasna_pot = None
                    self._pocisti_operacije()
                    self._nastavi_napredek_operacij(100, "Končano")
                    self._nastavi_prosto("Operacije uspešno izvedene.")
                    messagebox.showinfo(
                        "Uspeh",
                        f"Vse operacije uspešno izvedene!\n\nShranjeno v:\n{ciljna_pot}",
                    )
                    return

            self._nastavi_zasedeno("Združujem s pomočjo mkvmerge...")
            self._nastavi_napredek_operacij(None, "Združujem datoteke …")
            izhodna_zacasna_pot = self._nova_zacasna_mkv_pot(
                ciljna_pot, "output"
            )

            # Pripravi mkvmerge ukaz
            if "flatpak run" in self.mkvmerge:
                ukaz = self.mkvmerge.split() + ["-o", izhodna_zacasna_pot]
            else:
                ukaz = [self.mkvmerge, "-o", izhodna_zacasna_pot]

            # Sledi za odstranitev
            if sledi_za_odstranitev:
                vse_sledi = self._pridobi_informacije()
                video_sledi = [
                    mkv_track_id(s["index"])
                    for s in vse_sledi
                    if s.get("codec_type") == "video"
                    and str(s["index"]) not in sledi_za_odstranitev
                ]
                audio_sledi = [
                    mkv_track_id(s["index"])
                    for s in vse_sledi
                    if s.get("codec_type") == "audio"
                    and str(s["index"]) not in sledi_za_odstranitev
                ]
                sub_sledi = [
                    mkv_track_id(s["index"])
                    for s in vse_sledi
                    if s.get("codec_type") == "subtitle"
                    and str(s["index"]) not in sledi_za_odstranitev
                ]

                if video_sledi:
                    ukaz.extend(["-d", ",".join(video_sledi)])
                else:
                    ukaz.extend(["-D"])
                if audio_sledi:
                    ukaz.extend(["-a", ",".join(audio_sledi)])
                else:
                    ukaz.extend(["-A"])
                if sub_sledi:
                    ukaz.extend(["-s", ",".join(sub_sledi)])
                else:
                    ukaz.extend(["-S"])

            # Spremembe jezika
            for stevilka, jezik in spremembe_jezika.items():
                ukaz.extend(["--language", f"{mkv_track_id(stevilka)}:{jezik}"])

            # Spremembe naslova
            for stevilka, naslov in spremembe_naslova.items():
                ukaz.extend(["--track-name", f"{mkv_track_id(stevilka)}:{naslov}"])

            # Privzete sledi
            for vrsta, stevilka in privzete_sledi.items():
                if stevilka:
                    ukaz.extend(["--default-track", f"{mkv_track_id(stevilka)}:yes"])

            if zamenjaj_vse_podnapise:
                ukaz.extend(["--no-subtitles"])
            ukaz.append(vhodna_datoteka)

            # Dodatne datoteke
            for dat in dodatne_datoteke:
                if dat.get("jezik"):
                    ukaz.extend(["--language", f"0:{dat['jezik']}"])
                if dat.get("privzet"):
                    ukaz.extend(["--default-track", "0:yes"])
                ukaz.append(dat["pot"])

            self._izvedi_ukaz_z_osvezevanjem(ukaz)

            # Počisti začasne datoteke
            self._nastavi_napredek_operacij(None, "Zaključujem …")
            os.replace(izhodna_zacasna_pot, ciljna_pot)
            izhodna_zacasna_pot = None
            self._varno_odstrani(zacasna_pot)

            self._pocisti_operacije()
            self._nastavi_napredek_operacij(100, "Končano")
            self._nastavi_prosto("Operacije uspešno izvedene.")
            messagebox.showinfo(
                "Uspeh",
                f"Vse operacije uspešno izvedene!\n\nShranjeno v:\n{ciljna_pot}",
            )

        except (
            subprocess.CalledProcessError,
            OperacijaPrekinjena,
            OSError,
            RuntimeError,
        ) as e:
            if self._zapiranje:
                self._nastavi_prosto("Operacija prekinjena.")
                return
            napaka = self._opis_napake_procesa(e)
            self._nastavi_prosto("Napaka pri izvajanju.")
            messagebox.showerror("Napaka", f"Napaka pri izvajanju operacij:\n{napaka}")
        finally:
            self._varno_odstrani(zacasna_pot)
            self._varno_odstrani(izhodna_zacasna_pot)

    def _ustvari_podnapisi(self, okvir):
        """Ustvari zavihek za dodajanje podnapisov."""
        # Izbira datoteke podnapisov
        okvir_podnapis = ttk.LabelFrame(okvir, text="Datoteka podnapisov", padding=10)
        okvir_podnapis.pack(fill="x", pady=5)

        self.vnos_podnapis = ttk.Entry(okvir_podnapis, width=60)
        self.vnos_podnapis.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self._ustvari_gumb(okvir_podnapis, text="Izberi", command=self._izberi_podnapis).pack(
            side="left"
        )

        # Nastavitve
        okvir_nastavitve = ttk.LabelFrame(okvir, text="Nastavitve", padding=10)
        okvir_nastavitve.pack(fill="x", pady=5)

        ttk.Label(okvir_nastavitve, text="Jezik:").grid(
            row=0, column=0, sticky="w", pady=5
        )
        self.jezik_podnapis = ttk.Combobox(
            okvir_nastavitve,
            values=[
                "slv - Slovenščina",
                "eng - Angleščina",
                "hrv - Hrvaščina",
                "srp - Srbščina",
                "deu - Nemščina",
                "ita - Italijanščina",
            ],
            width=30,
        )
        self.jezik_podnapis.set("slv - Slovenščina")
        self.jezik_podnapis.grid(row=0, column=1, sticky="w", padx=10, pady=5)

        ttk.Label(okvir_nastavitve, text="Naslov:").grid(
            row=1, column=0, sticky="w", pady=5
        )
        self.naslov_podnapis = ttk.Entry(okvir_nastavitve, width=33)
        self.naslov_podnapis.grid(row=1, column=1, sticky="w", padx=10, pady=5)

        self.privzet_podnapis = tk.BooleanVar()
        ttk.Checkbutton(
            okvir_nastavitve,
            text="Nastavi kot privzet podnapis",
            variable=self.privzet_podnapis,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=5)

        self.zamenjaj_podnapise = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            okvir_nastavitve,
            text="Zamenjaj vse obstoječe podnapise",
            variable=self.zamenjaj_podnapise,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=5)

        self._ustvari_gumb(
            okvir,
            text="Dodaj podnapise",
            command=self._dodaj_podnapise,
            style="Accent.TButton",
        ).pack(
            pady=20
        )

    def _ustvari_pretvorbo(self, okvir):
        """Ustvari zavihek za pretvorbo."""
        # Audio pretvorba
        okvir_avdio = ttk.LabelFrame(okvir, text="Pretvorba zvoka", padding=10)
        okvir_avdio.pack(fill="x", pady=5)

        ttk.Label(okvir_avdio, text="Ciljni format:").grid(
            row=0, column=0, sticky="w", pady=5
        )
        self.avdio_format = ttk.Combobox(
            okvir_avdio,
            values=[
                "ac3",
                "aac",
                "mp3",
                "opus",
                "flac",
                "vorbis",
                "kopija (brez pretvorbe)",
            ],
            width=25,
        )
        self.avdio_format.set("ac3")
        self.avdio_format.grid(row=0, column=1, sticky="w", padx=10, pady=5)

        ttk.Label(okvir_avdio, text="Bitna hitrost:").grid(
            row=1, column=0, sticky="w", pady=5
        )
        self.avdio_bitrate = ttk.Combobox(
            okvir_avdio, values=["64k", "128k", "192k", "256k", "320k"], width=25
        )
        self.avdio_bitrate.set("192k")
        self.avdio_bitrate.grid(row=1, column=1, sticky="w", padx=10, pady=5)

        # Video pretvorba
        okvir_video = ttk.LabelFrame(okvir, text="Pretvorba videa", padding=10)
        okvir_video.pack(fill="x", pady=5)

        ttk.Label(okvir_video, text="Ciljni format:").grid(
            row=0, column=0, sticky="w", pady=5
        )
        self.video_format = ttk.Combobox(
            okvir_video,
            values=["h264", "h265/hevc", "vp9", "av1", "kopija (brez pretvorbe)"],
            width=25,
        )
        self.video_format.set("kopija (brez pretvorbe)")
        self.video_format.grid(row=0, column=1, sticky="w", padx=10, pady=5)

        ttk.Label(okvir_video, text="Kakovost (CRF):").grid(
            row=1, column=0, sticky="w", pady=5
        )
        self.video_crf = ttk.Combobox(
            okvir_video, values=["18 (visoka)", "23 (srednja)", "28 (nizka)"], width=25
        )
        self.video_crf.set("23 (srednja)")
        self.video_crf.grid(row=1, column=1, sticky="w", padx=10, pady=5)

        self._ustvari_gumb(
            okvir,
            text="Pretvori in shrani",
            command=self._pretvori,
            style="Accent.TButton",
        ).pack(
            pady=20
        )

    def _ustvari_odstranitev(self, okvir):
        """Ustvari zavihek za odstranjevanje sledi."""
        ttk.Label(okvir, text="Označite sledi za odstranitev:").pack(anchor="w", pady=5)

        stolpci = ("Izberi", "Št.", "Vrsta", "Kodek", "Jezik")
        self.drevo_odstrani = ttk.Treeview(
            okvir, columns=stolpci, show="headings", height=6
        )

        for stolpec in stolpci:
            self.drevo_odstrani.heading(stolpec, text=stolpec)

        self.drevo_odstrani.column("Izberi", width=60)
        self.drevo_odstrani.column("Št.", width=50)
        self.drevo_odstrani.column("Vrsta", width=100)
        self.drevo_odstrani.column("Kodek", width=150)
        self.drevo_odstrani.column("Jezik", width=100)

        self.drevo_odstrani.pack(fill="both", expand=True, pady=5)
        self.drevo_odstrani.bind("<Button-1>", self._preklopi_izbiro)

        self.izbrane_za_odstranitev = set()

        okvir_gumbi = ttk.Frame(okvir)
        okvir_gumbi.pack(fill="x", pady=10)

        self._ustvari_gumb(
            okvir_gumbi, text="Osveži seznam", command=self._osvezi_odstranitev
        ).pack(side="left", padx=5)
        self._ustvari_gumb(
            okvir_gumbi,
            text="Odstrani označene sledi",
            command=self._odstrani_sledi,
            style="Accent.TButton",
        ).pack(side="left", padx=5)

    def _ustvari_izdelavo(self, okvir):
        """Ustvari zavihek za izdelavo novega MKV."""
        # Seznam vhodnih datotek
        okvir_seznam = ttk.LabelFrame(okvir, text="Vhodne datoteke", padding=10)
        okvir_seznam.pack(fill="both", expand=True, pady=5)

        stolpci = ("Vrsta", "Datoteka", "Jezik")
        self.drevo_vhod = ttk.Treeview(
            okvir_seznam, columns=stolpci, show="headings", height=5
        )

        self.drevo_vhod.heading("Vrsta", text="Vrsta")
        self.drevo_vhod.heading("Datoteka", text="Datoteka")
        self.drevo_vhod.heading("Jezik", text="Jezik")

        self.drevo_vhod.column("Vrsta", width=80)
        self.drevo_vhod.column("Datoteka", width=450)
        self.drevo_vhod.column("Jezik", width=80)

        drsnik = ttk.Scrollbar(
            okvir_seznam, orient="vertical", command=self.drevo_vhod.yview
        )
        self.drevo_vhod.configure(yscrollcommand=drsnik.set)

        self.drevo_vhod.pack(side="left", fill="both", expand=True)
        drsnik.pack(side="right", fill="y")

        self.vhodne_datoteke = []

        # Gumbi za dodajanje
        okvir_dodaj = ttk.Frame(okvir)
        okvir_dodaj.pack(fill="x", pady=5)

        self._ustvari_gumb(
            okvir_dodaj, text="Dodaj video", command=lambda: self._dodaj_vhodno("video")
        ).pack(side="left", padx=5)
        self._ustvari_gumb(
            okvir_dodaj, text="Dodaj zvok", command=lambda: self._dodaj_vhodno("audio")
        ).pack(side="left", padx=5)
        self._ustvari_gumb(
            okvir_dodaj,
            text="Dodaj podnapise",
            command=lambda: self._dodaj_vhodno("podnapisi"),
        ).pack(side="left", padx=5)
        self._ustvari_gumb(
            okvir_dodaj, text="Odstrani izbrano", command=self._odstrani_vhodno
        ).pack(side="left", padx=5)
        self._ustvari_gumb(okvir_dodaj, text="Počisti vse", command=self._pocisti_vhodne).pack(
            side="left", padx=5
        )

        # Nastavitve
        okvir_nastavitve = ttk.LabelFrame(okvir, text="Nastavitve", padding=10)
        okvir_nastavitve.pack(fill="x", pady=5)

        ttk.Label(okvir_nastavitve, text="Naslov:").grid(
            row=0, column=0, sticky="w", pady=5
        )
        self.mkv_naslov = ttk.Entry(okvir_nastavitve, width=50)
        self.mkv_naslov.grid(row=0, column=1, sticky="w", padx=10, pady=5)

        self.kopiraj_metapodatke = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            okvir_nastavitve,
            text="Kopiraj metapodatke",
            variable=self.kopiraj_metapodatke,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=5)

        self._ustvari_gumb(
            okvir,
            text="Ustvari MKV",
            command=self._ustvari_mkv,
            style="Accent.TButton",
        ).pack(pady=15)

    def _dodaj_vhodno(self, vrsta):
        """Dodaj vhodno datoteko za izdelavo MKV."""
        if vrsta == "video":
            tipi = [
                (
                    "Video datoteke",
                    "*.mp4 *.avi *.mkv *.mov *.wmv *.flv *.webm *.m4v *.mpeg *.mpg",
                ),
                ("Vse datoteke", "*.*"),
            ]
            naslov = "Izberi video datoteko"
        elif vrsta == "audio":
            tipi = [
                (
                    "Zvočne datoteke",
                    "*.mp3 *.aac *.ac3 *.flac *.ogg *.wav *.m4a *.opus *.dts *.eac3",
                ),
                ("Vse datoteke", "*.*"),
            ]
            naslov = "Izberi zvočno datoteko"
        else:
            tipi = [
                ("Podnapisi", "*.srt *.ass *.ssa *.sub *.txt *.vtt"),
                ("Vse datoteke", "*.*"),
            ]
            naslov = "Izberi datoteko podnapisov"

        pot = self._odpri_dialog_datoteka(naslov=naslov, tipi=tipi)
        if pot:
            # Vprašaj za jezik
            jezik = self._vprasaj_jezik()

            self.vhodne_datoteke.append({"vrsta": vrsta, "pot": pot, "jezik": jezik})
            self.drevo_vhod.insert(
                "",
                "end",
                values=(
                    vrsta.capitalize() if vrsta != "audio" else "Zvok",
                    Path(pot).name,
                    jezik,
                ),
            )

    def _vprasaj_jezik(self):
        """Odpre dialog za izbiro jezika."""
        dialog = self._ustvari_dialog("Izberi jezik", 300, 120)

        ttk.Label(dialog, text="Jezik sledi:").pack(pady=10)

        izbira = ttk.Combobox(
            dialog,
            values=[
                "und - Nedoločen",
                "slv - Slovenščina",
                "eng - Angleščina",
                "hrv - Hrvaščina",
                "srp - Srbščina",
                "deu - Nemščina",
                "ita - Italijanščina",
                "fra - Francoščina",
                "spa - Španščina",
            ],
            width=25,
        )
        izbira.set("und - Nedoločen")
        izbira.pack(pady=5)

        rezultat = ["und"]

        def potrdi():
            rezultat[0] = izbira.get().split(" - ")[0]
            dialog.destroy()

        self._ustvari_gumb(dialog, text="Potrdi", command=potrdi).pack(pady=10)

        dialog.wait_window()
        return rezultat[0]

    def _odstrani_vhodno(self):
        """Odstrani izbrano vhodno datoteko."""
        izbrana = self.drevo_vhod.selection()
        if izbrana:
            indeks = self.drevo_vhod.index(izbrana[0])
            self.drevo_vhod.delete(izbrana[0])
            if indeks < len(self.vhodne_datoteke):
                del self.vhodne_datoteke[indeks]

    def _pocisti_vhodne(self):
        """Počisti vse vhodne datoteke."""
        for vrstica in self.drevo_vhod.get_children():
            self.drevo_vhod.delete(vrstica)
        self.vhodne_datoteke.clear()

    def _ustvari_mkv(self):
        """Ustvari novo MKV datoteko iz vhodnih datotek."""
        if not self.vhodne_datoteke:
            messagebox.showwarning("Opozorilo", "Dodajte vsaj eno vhodno datoteko.")
            return

        # Preveri, da je vsaj en video
        ima_video = any(d["vrsta"] == "video" for d in self.vhodne_datoteke)
        if not ima_video:
            if not messagebox.askyesno(
                "Brez videa", "Niste dodali video datoteke. Želite nadaljevati?"
            ):
                return

        if not self.mkvmerge:
            messagebox.showerror("Napaka", "mkvmerge ni nameščen.")
            return

        # Ciljna datoteka
        ciljna_pot = self._shrani_dialog_datoteka(
            naslov="Shrani MKV kot",
            privzeto_ime="nov_video.mkv",
            tipi=[("MKV datoteke", "*.mkv")],
        )

        if not ciljna_pot:
            return

        if not ciljna_pot.endswith(".mkv"):
            ciljna_pot += ".mkv"

        if not self._preveri_zapisljivost_cilja(ciljna_pot):
            return

        self._nastavi_zasedeno("Ustvarjam MKV...")
        izhodna_zacasna_pot = None

        try:
            izhodna_zacasna_pot = self._nova_zacasna_mkv_pot(
                ciljna_pot, "output"
            )
            if "flatpak run" in self.mkvmerge:
                ukaz = self.mkvmerge.split() + ["-o", izhodna_zacasna_pot]
            else:
                ukaz = [self.mkvmerge, "-o", izhodna_zacasna_pot]

            # Naslov
            naslov = self.mkv_naslov.get()
            if naslov:
                ukaz.extend(["--title", naslov])

            # Dodaj vhodne datoteke
            for datoteka in self.vhodne_datoteke:
                pot = datoteka["pot"]
                jezik = datoteka["jezik"]

                if jezik and jezik != "und":
                    ukaz.extend(["--language", f"0:{jezik}"])

                ukaz.append(pot)

            self._izvedi_ukaz_z_osvezevanjem(ukaz)
            os.replace(izhodna_zacasna_pot, ciljna_pot)
            izhodna_zacasna_pot = None
            self._nastavi_prosto("MKV ustvarjen.")
            messagebox.showinfo(
                "Uspeh", f"MKV uspešno ustvarjen!\n\nShranjeno v:\n{ciljna_pot}"
            )
        except (subprocess.CalledProcessError, OperacijaPrekinjena, OSError) as e:
            if self._zapiranje:
                self._nastavi_prosto("Operacija prekinjena.")
                return
            napaka = self._opis_napake_procesa(e)
            self._nastavi_prosto("Napaka pri ustvarjanju.")
            messagebox.showerror("Napaka", f"Napaka pri ustvarjanju MKV:\n{napaka}")
        finally:
            self._varno_odstrani(izhodna_zacasna_pot)

    def _ustvari_navodila(self, okvir):
        """Ustvari zavihek z navodili za uporabo."""
        # Ustvari okvir z drsnikom
        okvir_drsnik = ttk.Frame(okvir)
        okvir_drsnik.pack(fill="both", expand=True)

        platno = tk.Canvas(okvir_drsnik, highlightthickness=0, bg=self.barve["ozadje"])
        drsnik = ttk.Scrollbar(okvir_drsnik, orient="vertical", command=platno.yview)
        okvir_vsebina = ttk.Frame(platno)

        # ID okna za kasnejšo posodobitev širine
        okno_id = platno.create_window((0, 0), window=okvir_vsebina, anchor="nw")

        def _posodobi_sirina(event):
            platno.itemconfig(okno_id, width=event.width)

        def _posodobi_scroll(event):
            platno.configure(scrollregion=platno.bbox("all"))

        platno.bind("<Configure>", _posodobi_sirina)
        okvir_vsebina.bind("<Configure>", _posodobi_scroll)
        platno.configure(yscrollcommand=drsnik.set)

        # Omogoči drsenje z miškinim kolescem
        def _on_mousewheel(event):
            platno.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _on_mousewheel_linux(event):
            if event.num == 4:
                platno.yview_scroll(-1, "units")
            elif event.num == 5:
                platno.yview_scroll(1, "units")

        platno.bind_all("<MouseWheel>", _on_mousewheel)
        platno.bind_all("<Button-4>", _on_mousewheel_linux)
        platno.bind_all("<Button-5>", _on_mousewheel_linux)

        platno.pack(side="left", fill="both", expand=True)
        drsnik.pack(side="right", fill="y")

        # Večji font za navodila
        font_naslov = ("TkDefaultFont", 16, "bold")
        font_razdelek = ("TkDefaultFont", 11, "bold")
        font_besedilo = ("TkDefaultFont", 11)

        # Naslov
        ttk.Label(okvir_vsebina, text="Navodila za uporabo baC", font=font_naslov).pack(
            anchor="w", pady=(0, 15), padx=10
        )

        navodila = [
            (
                "Pregled sledi",
                [
                    "Ta zavihek prikazuje vse sledi (video, zvok, podnapisi) v odprti MKV datoteki.",
                    "Z desnim klikom na sled odprete kontekstni meni z možnostmi:",
                    "  • Odstrani sled - doda operacijo za odstranitev izbrane sledi",
                    "  • Spremeni jezik - spremeni jezikovno oznako sledi",
                    "  • Spremeni naslov - spremeni naslov/ime sledi",
                    "  • Nastavi kot privzeto - označi sled kot privzeto",
                    "  • Pretvori zvok - pretvori zvočno sled v drug format (AAC, AC3, MP3)",
                    "  • Pretvori video - pretvori izbrano video sled v H.264/AVC, H.265/HEVC ali VP9",
                    "",
                    "Pretvorba videa je namenjena izboljšanju združljivosti z napravami, kot so TV-ji.",
                    "H.264/AVC je običajno najbolj združljiva izbira.",
                    "Operacija se doda na seznam čakajočih operacij; kliknite 'Izvedi vse'",
                    "za uporabo vseh sprememb in shranjevanje nove MKV datoteke.",
                    "Klik zunaj popup menija ali tipka Escape meni zapre.",
                    "",
                    "Gumba '+ Podnapisi' in '+ Zvok' omogočata povleci-in-spusti datotek.",
                ],
            ),
            (
                "Dodaj podnapise",
                [
                    "Ta zavihek omogoča hitro dodajanje podnapisov v MKV datoteko.",
                    "",
                    "Koraki:",
                    "  1. Izberite datoteko podnapisov (.srt, .ass, .ssa, .sub, .vtt)",
                    "  2. Izberite jezik podnapisov iz spustnega seznama",
                    "  3. Po želji označite 'Nastavi kot privzet podnapis'",
                    "  4. Kliknite 'Dodaj podnapise'",
                    "",
                    "Podprti formati: SRT, ASS, SSA, SUB, VTT, TXT",
                ],
            ),
            (
                "Pretvori",
                [
                    "Ta zavihek omogoča pretvorbo zvočnih in video sledi.",
                    "",
                    "Pretvorba zvoka:",
                    "  • Izberite ciljni format (AAC, AC3, MP3, OPUS, FLAC, Vorbis)",
                    "  • Nastavite bitno hitrost (64k - 320k)",
                    "  • 'Kopija' ohrani izvirni format brez ponovnega kodiranja",
                    "",
                    "Pretvorba videa:",
                    "  • Izberite ciljni kodek (H.264, H.265/HEVC, VP9, AV1)",
                    "  • Nastavite kakovost CRF (nižja = boljša kakovost, večja datoteka)",
                    "  • 'Kopija' ohrani izvirni format (priporočeno za hitrost)",
                ],
            ),
            (
                "Odstrani sledi",
                [
                    "Ta zavihek omogoča odstranjevanje neželenih sledi iz MKV datoteke.",
                    "",
                    "Uporaba:",
                    "  1. Kliknite na vrstico za označitev/odznačitev sledi",
                    "  2. Označene sledi (☑) bodo odstranjene",
                    "  3. Kliknite 'Odstrani označene sledi' za izvedbo",
                    "",
                    "Uporabno za odstranitev nepotrebnih zvočnih sledi ali podnapisov.",
                ],
            ),
            (
                "Ustvari MKV",
                [
                    "Ta zavihek omogoča ustvarjanje novega MKV iz več vhodnih datotek.",
                    "",
                    "Koraki:",
                    "  1. Dodajte video datoteko (obvezno)",
                    "  2. Dodajte zvočne datoteke (neobvezno)",
                    "  3. Dodajte podnapise (neobvezno)",
                    "  4. Za vsako datoteko izberite jezik",
                    "  5. Po želji nastavite naslov MKV datoteke",
                    "  6. Kliknite 'Ustvari MKV'",
                    "",
                    "Podpira povleci-in-spusti datotek v seznam.",
                ],
            ),
            (
                "Hitro v MKV",
                [
                    "Ta zavihek omogoča hitro pretvorbo video datoteke v MKV.",
                    "",
                    "Samodejno zazna povezane datoteke (podnapisi, zvok) z enakim imenom.",
                    "",
                    "Koraki:",
                    "  1. Izberite ali povlecite video datoteko",
                    "  2. Program samodejno poišče povezane datoteke",
                    "  3. Odkljukajte datoteke, ki jih ne želite vključiti",
                    "  4. Nastavite jezik podnapisov",
                    "  5. Kliknite 'Pretvori v MKV'",
                    "",
                    "Možnosti:",
                    "  • Podnapisi kot privzeti - samodejno prikaže podnapise",
                    "  • Kopiraj video brez kodiranja - hitrejša pretvorba",
                    "  • Pretvori zvok v AAC - za boljšo združljivost",
                ],
            ),
            (
                "Splošni nasveti",
                [
                    "• Za odpiranje MKV datoteke uporabite gumb 'Odpri MKV' na vrhu",
                    "• Povleci-in-spusti deluje na večini vnosnih polj",
                    "• Program potrebuje nameščena orodja: ffmpeg, ffprobe, mkvmerge",
                    "• Izvirne datoteke se ohranijo - ustvari se nova datoteka",
                    "",
                    "Ukazna vrstica:",
                    "  bac       - Zaženi grafični vmesnik",
                    "  bac -q    - Hitro združi video+podnapisi v MKV",
                    "  bac -qq   - Kot -q, ampak izbriše izvorne datoteke",
                ],
            ),
        ]

        for naslov, vrstice in navodila:
            okvir_razdelek = ttk.LabelFrame(okvir_vsebina, text=naslov, padding=10)
            okvir_razdelek.pack(fill="x", pady=5, padx=10, expand=True)

            for vrstica in vrstice:
                lbl = ttk.Label(
                    okvir_razdelek,
                    text=vrstica,
                    font=font_besedilo,
                    wraplength=800,
                    justify="left",
                )
                lbl.pack(anchor="w", fill="x")

                # Dinamično prilagajanje wraplength
                def _posodobi_wrap(event, label=lbl):
                    label.configure(wraplength=event.width - 20)

                lbl.bind("<Configure>", _posodobi_wrap)

        # Glava z informacijami o projektu
        okvir_glava = ttk.Frame(okvir_vsebina)
        okvir_glava.pack(fill="x", pady=(20, 10), padx=5)

        ttk.Separator(okvir_glava, orient="horizontal").pack(fill="x", pady=(0, 10))

        ttk.Label(
            okvir_glava, text="Idejni vodja: BArko", font=("TkDefaultFont", 9)
        ).pack(anchor="center")
        ttk.Label(
            okvir_glava, text="Programiranje: BArko & SimOne", font=("TkDefaultFont", 9)
        ).pack(anchor="center")
        ttk.Label(
            okvir_glava, text="Izdelava: Jan, 2026", font=("TkDefaultFont", 9)
        ).pack(anchor="center")
        ttk.Label(
            okvir_glava, text=f"Verzija: {verzija}", font=("TkDefaultFont", 9)
        ).pack(anchor="center")

    def _ustvari_hitro_pretvorbo(self, okvir):
        """Ustvari zavihek za hitro pretvorbo v MKV."""
        ttk.Label(
            okvir,
            text="Hitro pretvori video datoteko v MKV z avtomatskim zaznavanjem podnapisov.",
            wraplength=600,
        ).pack(anchor="w", pady=5)

        # Izbira video datoteke
        okvir_video = ttk.LabelFrame(okvir, text="Video datoteka", padding=10)
        okvir_video.pack(fill="x", pady=5)

        self.vnos_hitro_video = ttk.Entry(okvir_video, width=60)
        self.vnos_hitro_video.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self._ustvari_gumb(okvir_video, text="Izberi", command=self._izberi_hitro_video).pack(
            side="left"
        )

        # Najdene datoteke
        okvir_najdene = ttk.LabelFrame(
            okvir, text="Najdene povezane datoteke", padding=10
        )
        okvir_najdene.pack(fill="both", expand=True, pady=5)

        stolpci = ("Uporabi", "Vrsta", "Datoteka")
        self.drevo_hitro = ttk.Treeview(
            okvir_najdene, columns=stolpci, show="headings", height=5
        )

        self.drevo_hitro.heading("Uporabi", text="Uporabi")
        self.drevo_hitro.heading("Vrsta", text="Vrsta")
        self.drevo_hitro.heading("Datoteka", text="Datoteka")

        self.drevo_hitro.column("Uporabi", width=60)
        self.drevo_hitro.column("Vrsta", width=100)
        self.drevo_hitro.column("Datoteka", width=450)

        self.drevo_hitro.pack(fill="both", expand=True)
        self.drevo_hitro.bind("<Button-1>", self._preklopi_hitro_izbiro)

        self.hitro_datoteke = []
        self.hitro_izbrane = set()

        # Nastavitve
        okvir_nast = ttk.LabelFrame(okvir, text="Nastavitve", padding=10)
        okvir_nast.pack(fill="x", pady=5)

        ttk.Label(okvir_nast, text="Jezik podnapisov:").grid(
            row=0, column=0, sticky="w", pady=5
        )
        self.hitro_jezik = ttk.Combobox(
            okvir_nast,
            values=[
                "slv - Slovenščina",
                "eng - Angleščina",
                "hrv - Hrvaščina",
                "und - Nedoločen",
            ],
            width=25,
        )
        self.hitro_jezik.set("slv - Slovenščina")
        self.hitro_jezik.grid(row=0, column=1, sticky="w", padx=10, pady=5)

        self.hitro_privzet = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            okvir_nast, text="Podnapisi kot privzeti", variable=self.hitro_privzet
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=5)

        self.hitro_kopiraj = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            okvir_nast,
            text="Kopiraj video brez ponovnega kodiranja (hitrejše)",
            variable=self.hitro_kopiraj,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=5)

        self.hitro_aac = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            okvir_nast,
            text="Pretvori zvok v AC3 (če ni že AC3)",
            variable=self.hitro_aac,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=5)

        self.hitro_izpusti_podnapise = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            okvir_nast,
            text="Izpusti ostale podnapise iz vira",
            variable=self.hitro_izpusti_podnapise,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=5)

        self.hitro_samo_prvi_zvok = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            okvir_nast,
            text="Ohrani samo prvi zvok iz vira",
            variable=self.hitro_samo_prvi_zvok,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=5)

        # Okvir za gumb na dnu
        okvir_gumb = ttk.Frame(okvir)
        okvir_gumb.pack(fill="x", pady=10)

        gumb_pretvori = self._ustvari_gumb(
            okvir_gumb,
            text="▶ Pretvori v MKV",
            command=self._izvedi_hitro_pretvorbo,
            style="Accent.TButton",
        )
        gumb_pretvori.pack(pady=5, ipadx=20, ipady=5)

    def _izberi_hitro_video(self):
        """Izbere video datoteko in poišče povezane podnapise."""
        pot = self._odpri_dialog_datoteka(
            naslov="Izberi video datoteko",
            tipi=[
                (
                    "Video datoteke",
                    "*.mp4 *.avi *.mov *.wmv *.flv *.webm *.m4v *.mpeg *.mpg *.mkv",
                )
            ],
        )
        if not pot:
            return

        self.vnos_hitro_video.delete(0, tk.END)
        self.vnos_hitro_video.insert(0, pot)

        # Počisti prejšnje
        for vrstica in self.drevo_hitro.get_children():
            self.drevo_hitro.delete(vrstica)
        self.hitro_datoteke.clear()
        self.hitro_izbrane.clear()

        # Poišči povezane datoteke
        mapa = os.path.dirname(pot)
        osnovni_ime = Path(pot).stem

        # Končnice podnapisov
        koncnice_sub = [".srt", ".ass", ".ssa", ".sub", ".vtt", ".txt"]
        # Končnice zvoka
        koncnice_audio = [
            ".mp3",
            ".aac",
            ".ac3",
            ".flac",
            ".ogg",
            ".wav",
            ".m4a",
            ".opus",
            ".dts",
        ]

        najdene = []

        # Poišči datoteke z istim osnovnim imenom
        for datoteka in os.listdir(mapa):
            dat_pot = os.path.join(mapa, datoteka)
            if not os.path.isfile(dat_pot) or dat_pot == pot:
                continue

            dat_stem = Path(datoteka).stem
            dat_suffix = Path(datoteka).suffix.lower()

            # Preveri ali se ime ujema (tudi z dodatki kot .sl, .en, itd.)
            if (
                dat_stem == osnovni_ime
                or dat_stem.startswith(osnovni_ime + ".")
                or dat_stem.startswith(osnovni_ime + "_")
            ):
                if dat_suffix in koncnice_sub:
                    najdene.append(
                        {"vrsta": "Podnapisi", "pot": dat_pot, "ime": datoteka}
                    )
                elif dat_suffix in koncnice_audio:
                    najdene.append({"vrsta": "Zvok", "pot": dat_pot, "ime": datoteka})

        # Dodaj video
        self.hitro_datoteke.append(
            {"vrsta": "Video", "pot": pot, "ime": Path(pot).name}
        )
        self.hitro_izbrane.add("0")
        self.drevo_hitro.insert(
            "", "end", iid="0", values=("☑", "Video", Path(pot).name)
        )

        # Dodaj najdene
        for i, dat in enumerate(najdene, start=1):
            self.hitro_datoteke.append(dat)
            self.hitro_izbrane.add(str(i))
            self.drevo_hitro.insert(
                "", "end", iid=str(i), values=("☑", dat["vrsta"], dat["ime"])
            )

        stevilo_sub = sum(1 for d in najdene if d["vrsta"] == "Podnapisi")
        self.status.config(
            text=f"Najdenih {len(najdene)} povezanih datotek ({stevilo_sub} podnapisov)"
        )

    def _preklopi_hitro_izbiro(self, dogodek):
        """Preklopi izbiro datoteke."""
        vrstica = self.drevo_hitro.identify_row(dogodek.y)
        stolpec = self.drevo_hitro.identify_column(dogodek.x)

        if vrstica and stolpec == "#1":
            if vrstica in self.hitro_izbrane:
                self.hitro_izbrane.discard(vrstica)
                vrednosti = list(self.drevo_hitro.item(vrstica, "values"))
                vrednosti[0] = "☐"
                self.drevo_hitro.item(vrstica, values=vrednosti)
            else:
                self.hitro_izbrane.add(vrstica)
                vrednosti = list(self.drevo_hitro.item(vrstica, "values"))
                vrednosti[0] = "☑"
                self.drevo_hitro.item(vrstica, values=vrednosti)

    def _pridobi_audio_podatke(self, pot):
        """Pridobi audio kodek in indeks prvega audio streama - vrne (kodek, indeks)."""
        if not self.ffprobe:
            return None, None

        try:
            if "flatpak run" in self.ffprobe:
                deli = self.ffprobe.split()
                ukaz = deli + [
                    "-v", "quiet", "-print_format", "json",
                    "-show_streams", pot,
                ]
            else:
                ukaz = [
                    self.ffprobe,
                    "-v", "quiet", "-print_format", "json",
                    "-show_streams", pot,
                ]

            if self._gui_zaklenjen:
                stdout, _ = self._izvedi_ukaz_z_osvezevanjem(ukaz)
                podatki = json.loads(stdout.decode())
            else:
                rezultat = subprocess.run(
                    ukaz, capture_output=True, text=True, check=True
                )
                podatki = json.loads(rezultat.stdout)
            for sled in podatki.get("streams", []):
                if sled.get("codec_type") == "audio":
                    return sled.get("codec_name"), sled.get("index")
            return None, None
        except Exception:
            return None, None

    def _izvedi_hitro_pretvorbo(self):
        """Izvede hitro pretvorbo v MKV."""
        if not self.hitro_datoteke:
            messagebox.showwarning("Opozorilo", "Najprej izberite video datoteko.")
            return

        if not self.hitro_izbrane:
            messagebox.showwarning("Opozorilo", "Označite vsaj eno datoteko.")
            return

        if not self.mkvmerge:
            messagebox.showerror("Napaka", "mkvmerge ni nameščen.")
            return

        # Izbrane datoteke
        izbrane = [
            dict(self.hitro_datoteke[int(i)])
            for i in sorted(self.hitro_izbrane, key=int)
            if int(i) < len(self.hitro_datoteke)
        ]

        if not any(d["vrsta"] == "Video" for d in izbrane):
            messagebox.showwarning("Opozorilo", "Označite video datoteko.")
            return

        # Ciljna datoteka
        video_pot = next(d["pot"] for d in izbrane if d["vrsta"] == "Video")
        osnovni_dir = os.path.dirname(video_pot)
        osnovni_ime = Path(video_pot).stem

        ciljna_pot = self._shrani_dialog_datoteka(
            naslov="Shrani MKV kot",
            zacetna_mapa=osnovni_dir,
            privzeto_ime=f"{osnovni_ime}.mkv",
            tipi=[("MKV datoteke", "*.mkv")],
        )

        if not ciljna_pot:
            return

        if not ciljna_pot.endswith(".mkv"):
            ciljna_pot += ".mkv"

        if not self._preveri_zapisljivost_cilja(ciljna_pot):
            return

        self._nastavi_zasedeno("Pretvarjam v MKV...")
        zacasna_pot = None
        izhodna_zacasna_pot = None

        try:
            # Preveri audio kodek in indeks prvega audio streama
            video_pot = next(d["pot"] for d in izbrane if d["vrsta"] == "Video")
            audio_kodek, prvi_audio_id = self._pridobi_audio_podatke(video_pot)
            mkv_audio_id = None
            if self.hitro_samo_prvi_zvok.get() and prvi_audio_id is not None:
                mkv_track_map = self._pridobi_mkvmerge_track_map(video_pot)
                mkv_audio_id = mkv_track_map.get(str(prvi_audio_id))
                if mkv_audio_id is None:
                    raise RuntimeError(
                        "Izbrane zvočne sledi ni mogoče zanesljivo najti v mkvmerge."
                    )
            potrebna_pretvorba_audio = (
                self.hitro_aac.get()
                and audio_kodek
                and audio_kodek.lower() not in ["ac3"]
            )

            jezik = (
                self.hitro_jezik.get().split(" - ")[0]
                if self.hitro_jezik.get()
                else "und"
            )

            # Če je potrebna pretvorba audio, uporabi ffmpeg najprej
            if potrebna_pretvorba_audio and self.ffmpeg:
                self._nastavi_zasedeno("Pretvarjam zvok v AC3...")

                # Začasna datoteka za pretvorjen video
                zacasna_pot = self._nova_zacasna_mkv_pot(ciljna_pot, "temp_audio")

                if "flatpak run" in self.ffmpeg:
                    ukaz_ff = self.ffmpeg.split() + ["-i", video_pot, "-y"]
                else:
                    ukaz_ff = [self.ffmpeg, "-i", video_pot, "-y"]

                # Kopiraj video, pretvori audio
                if self.hitro_kopiraj.get():
                    ukaz_ff.extend(["-c:v", "copy"])
                else:
                    ukaz_ff.extend(["-c:v", "libx264", "-crf", "23"])

                ukaz_ff.extend(["-c:a", "ac3", "-b:a", "192k"])
                ukaz_ff.append(zacasna_pot)

                self._izvedi_ukaz_z_osvezevanjem(ukaz_ff)

                # Posodobi pot videa
                for dat in izbrane:
                    if dat["vrsta"] == "Video":
                        dat["pot"] = zacasna_pot
                        dat["zacasna"] = True
                        break

            self._nastavi_zasedeno("Združujem v MKV...")

            # Združi z mkvmerge
            izhodna_zacasna_pot = self._nova_zacasna_mkv_pot(
                ciljna_pot, "output"
            )
            if "flatpak run" in self.mkvmerge:
                ukaz = self.mkvmerge.split() + ["-o", izhodna_zacasna_pot]
            else:
                ukaz = [self.mkvmerge, "-o", izhodna_zacasna_pot]

            # Dodaj datoteke
            for dat in izbrane:
                if dat["vrsta"] == "Video":
                    if self.hitro_izpusti_podnapise.get():
                        ukaz.extend(["--no-subtitles"])
                    if (
                        self.hitro_samo_prvi_zvok.get()
                        and not potrebna_pretvorba_audio
                        and mkv_audio_id is not None
                    ):
                        ukaz.extend(["--audio-tracks", str(mkv_audio_id)])
                elif dat["vrsta"] == "Podnapisi":
                    if jezik:
                        ukaz.extend(["--language", f"0:{jezik}"])
                    if self.hitro_privzet.get():
                        ukaz.extend(["--default-track", "0:yes"])

                ukaz.append(dat["pot"])

            self._izvedi_ukaz_z_osvezevanjem(ukaz)
            os.replace(izhodna_zacasna_pot, ciljna_pot)
            izhodna_zacasna_pot = None

            # Počisti začasne datoteke
            self._varno_odstrani(zacasna_pot)

            self._nastavi_prosto("Pretvorba končana.")
            messagebox.showinfo(
                "Uspeh", f"MKV uspešno ustvarjen!\n\nShranjeno v:\n{ciljna_pot}"
            )
        except (
            subprocess.CalledProcessError,
            OperacijaPrekinjena,
            OSError,
            RuntimeError,
        ) as e:
            if self._zapiranje:
                self._nastavi_prosto("Operacija prekinjena.")
                return
            napaka = self._opis_napake_procesa(e)
            self._nastavi_prosto("Napaka pri pretvorbi.")
            messagebox.showerror("Napaka", f"Napaka pri pretvorbi:\n{napaka}")
        finally:
            self._varno_odstrani(zacasna_pot)
            self._varno_odstrani(izhodna_zacasna_pot)

    def _odpri_mkv(self):
        """Odpre dialog za izbiro MKV datoteke."""
        pot = self._odpri_dialog_datoteka(
            naslov="Izberi MKV datoteko", tipi=[("MKV datoteke", "*.mkv")]
        )
        if pot:
            self.mkv_pot = pot
            self.vnos_pot.delete(0, tk.END)
            self.vnos_pot.insert(0, pot)
            self._osvezi_sledi()
            self._osvezi_odstranitev()
            self.status.config(text=f"Odprto: {Path(pot).name}")

    def _ukaz_orodja(self, orodje, *argumenti):
        """Sestavi ukaz kot seznam argumentov, tudi za Flatpak orodja."""
        if isinstance(orodje, str) and orodje.startswith("flatpak run "):
            osnovni = orodje.split()
        else:
            osnovni = [orodje]
        return osnovni + list(argumenti)

    def _pridobi_sledi_za_pot(self, pot):
        """Prebere FFprobe sledi za poljubno pot."""
        if not self.ffprobe:
            return []
        ukaz = self._ukaz_orodja(
            self.ffprobe,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            pot,
        )
        if self._gui_zaklenjen:
            stdout, _ = self._izvedi_ukaz_z_osvezevanjem(ukaz)
            podatki = json.loads(stdout.decode())
        else:
            rezultat = subprocess.run(ukaz, capture_output=True, text=True, check=True)
            podatki = json.loads(rezultat.stdout)
        return podatki.get("streams", [])

    def _pridobi_mkvmerge_track_map(self, pot, ffprobe_sledi=None):
        """Preslika FFprobe stream indekse v mkvmerge track ID-je.

        FFprobe indeksi so globalni stream indeksi, mkvmerge pa uporablja
        track ID-je, ki so ločeni po posameznem vhodu. Preslikava temelji na
        vrstnem redu sledi znotraj iste vrste (video, audio, subtitles).
        """
        if not self.mkvmerge:
            return {}

        ffprobe_sledi = (
            self._pridobi_sledi_za_pot(pot)
            if ffprobe_sledi is None
            else ffprobe_sledi
        )
        ukaz = self._ukaz_orodja(self.mkvmerge, "-J", pot)
        if self._gui_zaklenjen:
            stdout, _ = self._izvedi_ukaz_z_osvezevanjem(ukaz)
            podatki = json.loads(stdout.decode())
        else:
            rezultat = subprocess.run(ukaz, capture_output=True, text=True, check=True)
            podatki = json.loads(rezultat.stdout)

        vrsta_mkvmerge = {
            "video": "video",
            "audio": "audio",
            "subtitles": "subtitle",
        }
        mkvmerge_po_vrsti = {"video": [], "audio": [], "subtitle": []}
        for sled in podatki.get("tracks", []):
            vrsta = vrsta_mkvmerge.get(sled.get("type"))
            if vrsta in mkvmerge_po_vrsti:
                mkvmerge_po_vrsti[vrsta].append(str(sled["id"]))

        ffprobe_po_vrsti = {"video": [], "audio": [], "subtitle": []}
        for sled in ffprobe_sledi:
            vrsta = sled.get("codec_type")
            if vrsta in ffprobe_po_vrsti:
                ffprobe_po_vrsti[vrsta].append(str(sled["index"]))

        preslikava = {}
        for vrsta in ffprobe_po_vrsti:
            for ffprobe_id, mkvmerge_id in zip(
                ffprobe_po_vrsti[vrsta], mkvmerge_po_vrsti[vrsta]
            ):
                preslikava[ffprobe_id] = mkvmerge_id
        return preslikava

    def _pridobi_informacije(self, prisilno=False):
        """Pridobi informacije o sledeh v MKV datoteki."""
        if not self.mkv_pot or not self.ffprobe:
            return []

        if (
            not prisilno
            and self._predpomnjena_mkv_pot == self.mkv_pot
            and self._predpomnjene_sledi is not None
        ):
            return self._predpomnjene_sledi

        try:
            if "flatpak run" in self.ffprobe:
                deli = self.ffprobe.split()
                ukaz = deli + [
                    "-v",
                    "quiet",
                    "-print_format",
                    "json",
                    "-show_streams",
                    self.mkv_pot,
                ]
            else:
                ukaz = [
                    self.ffprobe,
                    "-v",
                    "quiet",
                    "-print_format",
                    "json",
                    "-show_streams",
                    self.mkv_pot,
                ]
            if self._gui_zaklenjen:
                stdout, _ = self._izvedi_ukaz_z_osvezevanjem(ukaz)
                podatki = json.loads(stdout.decode())
            else:
                rezultat = subprocess.run(
                    ukaz, capture_output=True, text=True, check=True
                )
                podatki = json.loads(rezultat.stdout)
            sledi = podatki.get("streams", [])
            self._predpomnjena_mkv_pot = self.mkv_pot
            self._predpomnjene_sledi = sledi
            return sledi
        except Exception as e:
            messagebox.showerror("Napaka", f"Napaka pri branju datoteke:\n{e}")
            return []

    def _osvezi_sledi(self, prisilno=False):
        """Osveži seznam sledi."""
        for vrstica in self.drevo_sledi.get_children():
            self.drevo_sledi.delete(vrstica)

        self.stevilke_sledi = []
        sledi = self._pridobi_informacije(prisilno=prisilno)

        prevod_vrste = {"video": "Video", "audio": "Zvok", "subtitle": "Podnapisi"}

        for sled in sledi:
            stevilka = sled.get("index", "?")
            vrsta = prevod_vrste.get(
                sled.get("codec_type", ""), sled.get("codec_type", "")
            )
            kodek = sled.get("codec_name", "neznan")
            jezik = sled.get("tags", {}).get("language", "")
            naslov = sled.get("tags", {}).get("title", "")

            self.drevo_sledi.insert(
                "", "end", values=(stevilka, vrsta, kodek, jezik, naslov)
            )
            self.stevilke_sledi.append(stevilka)

    def _osvezi_odstranitev(self):
        """Osveži seznam sledi za odstranitev."""
        for vrstica in self.drevo_odstrani.get_children():
            self.drevo_odstrani.delete(vrstica)

        self.izbrane_za_odstranitev.clear()
        sledi = self._pridobi_informacije()

        prevod_vrste = {"video": "Video", "audio": "Zvok", "subtitle": "Podnapisi"}

        for sled in sledi:
            stevilka = sled.get("index", "?")
            vrsta = prevod_vrste.get(
                sled.get("codec_type", ""), sled.get("codec_type", "")
            )
            kodek = sled.get("codec_name", "neznan")
            jezik = sled.get("tags", {}).get("language", "")

            self.drevo_odstrani.insert(
                "",
                "end",
                iid=str(stevilka),
                values=("☐", stevilka, vrsta, kodek, jezik),
            )

    def _preklopi_izbiro(self, dogodek):
        """Preklopi izbiro sledi za odstranitev."""
        vrstica = self.drevo_odstrani.identify_row(dogodek.y)
        stolpec = self.drevo_odstrani.identify_column(dogodek.x)

        if vrstica and stolpec == "#1":
            if vrstica in self.izbrane_za_odstranitev:
                self.izbrane_za_odstranitev.discard(vrstica)
                vrednosti = list(self.drevo_odstrani.item(vrstica, "values"))
                vrednosti[0] = "☐"
                self.drevo_odstrani.item(vrstica, values=vrednosti)
            else:
                self.izbrane_za_odstranitev.add(vrstica)
                vrednosti = list(self.drevo_odstrani.item(vrstica, "values"))
                vrednosti[0] = "☑"
                self.drevo_odstrani.item(vrstica, values=vrednosti)

    def _izberi_podnapis(self):
        """Odpre dialog za izbiro datoteke podnapisov."""
        pot = self._odpri_dialog_datoteka(
            naslov="Izberi datoteko podnapisov",
            tipi=[("Podnapisi", "*.srt *.ass *.ssa *.sub *.txt")],
        )
        if pot:
            self.vnos_podnapis.delete(0, tk.END)
            self.vnos_podnapis.insert(0, pot)

    def _dodaj_podnapise(self):
        """Doda podnapise v MKV datoteko."""
        if not self.mkv_pot:
            messagebox.showwarning("Opozorilo", "Najprej odprite MKV datoteko.")
            return

        pot_podnapis = self.vnos_podnapis.get()
        if not pot_podnapis or not os.path.exists(pot_podnapis):
            messagebox.showwarning(
                "Opozorilo", "Izberite veljavno datoteko podnapisov."
            )
            return

        if not self.mkvmerge:
            messagebox.showerror("Napaka", "mkvmerge ni nameščen.")
            return

        # Ciljna datoteka
        osnovni_dir = os.path.dirname(self.mkv_pot)
        osnovni_ime = Path(self.mkv_pot).stem
        ciljna_pot = self._shrani_dialog_datoteka(
            naslov="Shrani kot",
            zacetna_mapa=osnovni_dir,
            privzeto_ime=f"_{osnovni_ime}.mkv",
            tipi=[("MKV datoteke", "*.mkv")],
        )

        if not ciljna_pot:
            return

        if not ciljna_pot.endswith(".mkv"):
            ciljna_pot += ".mkv"

        if not self._preveri_zapisljivost_cilja(ciljna_pot):
            return

        # Jezik
        jezik = (
            self.jezik_podnapis.get().split(" - ")[0]
            if self.jezik_podnapis.get()
            else "und"
        )
        naslov = self.naslov_podnapis.get()

        self._nastavi_zasedeno("Dodajam podnapise...")
        izhodna_zacasna_pot = None

        try:
            izhodna_zacasna_pot = self._nova_zacasna_mkv_pot(
                ciljna_pot, "output"
            )
            if "flatpak run" in self.mkvmerge:
                ukaz = self.mkvmerge.split() + ["-o", izhodna_zacasna_pot]
            else:
                ukaz = [self.mkvmerge, "-o", izhodna_zacasna_pot]

            if self.zamenjaj_podnapise.get():
                ukaz.extend(["--no-subtitles"])
            ukaz.append(self.mkv_pot)

            if jezik:
                ukaz.extend(["--language", f"0:{jezik}"])
            if naslov:
                ukaz.extend(["--track-name", f"0:{naslov}"])
            if self.privzet_podnapis.get():
                ukaz.extend(["--default-track", "0:yes"])

            ukaz.append(pot_podnapis)

            self._izvedi_ukaz_z_osvezevanjem(ukaz)
            os.replace(izhodna_zacasna_pot, ciljna_pot)
            izhodna_zacasna_pot = None
            self._nastavi_prosto("Podnapisi dodani.")
            messagebox.showinfo(
                "Uspeh", f"Podnapisi uspešno dodani!\n\nShranjeno v:\n{ciljna_pot}"
            )
        except (subprocess.CalledProcessError, OperacijaPrekinjena, OSError) as e:
            if self._zapiranje:
                self._nastavi_prosto("Operacija prekinjena.")
                return
            self._nastavi_prosto("Napaka pri dodajanju.")
            messagebox.showerror(
                "Napaka",
                f"Napaka pri dodajanju podnapisov:\n{self._opis_napake_procesa(e)}",
            )
        finally:
            self._varno_odstrani(izhodna_zacasna_pot)

    def _pretvori(self):
        """Pretvori avdio/video sledi."""
        if not self.mkv_pot:
            messagebox.showwarning("Opozorilo", "Najprej odprite MKV datoteko.")
            return

        if not self.ffmpeg:
            messagebox.showerror("Napaka", "ffmpeg ni nameščen.")
            return

        # Ciljna datoteka
        osnovni_dir = os.path.dirname(self.mkv_pot)
        osnovni_ime = Path(self.mkv_pot).stem
        ciljna_pot = self._shrani_dialog_datoteka(
            naslov="Shrani kot",
            zacetna_mapa=osnovni_dir,
            privzeto_ime=f"_{osnovni_ime}.mkv",
            tipi=[("MKV datoteke", "*.mkv")],
        )

        if not ciljna_pot:
            return

        if not ciljna_pot.endswith(".mkv"):
            ciljna_pot += ".mkv"

        if not self._preveri_zapisljivost_cilja(ciljna_pot):
            return

        self._nastavi_zasedeno("Pretvarjam...")
        izhodna_zacasna_pot = None

        try:
            if "flatpak run" in self.ffmpeg:
                ukaz = self.ffmpeg.split() + ["-i", self.mkv_pot, "-y"]
            else:
                ukaz = [self.ffmpeg, "-i", self.mkv_pot, "-y"]

            # Video kodek
            video_izbira = self.video_format.get()
            if "kopija" in video_izbira:
                ukaz.extend(["-c:v", "copy"])
            else:
                if "h264" in video_izbira:
                    ukaz.extend(["-c:v", "libx264"])
                elif "h265" in video_izbira or "hevc" in video_izbira:
                    ukaz.extend(["-c:v", "libx265"])
                elif "vp9" in video_izbira:
                    ukaz.extend(["-c:v", "libvpx-vp9"])
                elif "av1" in video_izbira:
                    ukaz.extend(["-c:v", "libaom-av1"])

                # CRF
                crf = self.video_crf.get().split(" ")[0]
                ukaz.extend(["-crf", crf])

            # Audio kodek
            avdio_izbira = self.avdio_format.get()
            if "kopija" in avdio_izbira:
                ukaz.extend(["-c:a", "copy"])
            else:
                kodeki = {
                    "aac": "aac",
                    "ac3": "ac3",
                    "mp3": "libmp3lame",
                    "opus": "libopus",
                    "flac": "flac",
                    "vorbis": "libvorbis",
                }
                ukaz.extend(["-c:a", kodeki.get(avdio_izbira, "ac3")])
                ukaz.extend(["-b:a", self.avdio_bitrate.get()])

            # Kopiraj podnapise
            ukaz.extend(["-c:s", "copy"])

            izhodna_zacasna_pot = self._nova_zacasna_mkv_pot(
                ciljna_pot, "output"
            )
            ukaz.append(izhodna_zacasna_pot)

            self._izvedi_ukaz_z_osvezevanjem(ukaz)
            os.replace(izhodna_zacasna_pot, ciljna_pot)
            izhodna_zacasna_pot = None
            self._nastavi_prosto("Pretvorba končana.")
            messagebox.showinfo(
                "Uspeh", f"Pretvorba uspešna!\n\nShranjeno v:\n{ciljna_pot}"
            )
        except (subprocess.CalledProcessError, OperacijaPrekinjena, OSError) as e:
            if self._zapiranje:
                self._nastavi_prosto("Operacija prekinjena.")
                return
            self._nastavi_prosto("Napaka pri pretvorbi.")
            messagebox.showerror(
                "Napaka",
                f"Napaka pri pretvorbi:\n{self._opis_napake_procesa(e)}",
            )
        finally:
            self._varno_odstrani(izhodna_zacasna_pot)

    def _odstrani_sledi(self):
        """Odstrani označene sledi."""
        if not self.mkv_pot:
            messagebox.showwarning("Opozorilo", "Najprej odprite MKV datoteko.")
            return

        if not self.izbrane_za_odstranitev:
            messagebox.showwarning(
                "Opozorilo", "Označite vsaj eno sled za odstranitev."
            )
            return

        if not self.ffmpeg:
            messagebox.showerror("Napaka", "ffmpeg ni nameščen.")
            return

        if not self.ffprobe:
            messagebox.showerror("Napaka", "ffprobe ni nameščen.")
            return

        # Ciljna datoteka
        osnovni_dir = os.path.dirname(self.mkv_pot)
        osnovni_ime = Path(self.mkv_pot).stem
        ciljna_pot = self._shrani_dialog_datoteka(
            naslov="Shrani kot",
            zacetna_mapa=osnovni_dir,
            privzeto_ime=f"_{osnovni_ime}.mkv",
            tipi=[("MKV datoteke", "*.mkv")],
        )

        if not ciljna_pot:
            return

        if not ciljna_pot.endswith(".mkv"):
            ciljna_pot += ".mkv"

        if not self._preveri_zapisljivost_cilja(ciljna_pot):
            return

        self._nastavi_zasedeno("Odstranjujem sledi...")
        izhodna_zacasna_pot = None

        try:
            # Pridobi vse sledi
            vse_sledi = self._pridobi_informacije()
            ohrani = [
                str(s.get("index"))
                for s in vse_sledi
                if str(s.get("index")) not in self.izbrane_za_odstranitev
            ]
            if not ohrani:
                raise RuntimeError("Vsaj ena sled mora ostati v izhodni datoteki.")

            if "flatpak run" in self.ffmpeg:
                ukaz = self.ffmpeg.split() + ["-i", self.mkv_pot, "-y"]
            else:
                ukaz = [self.ffmpeg, "-i", self.mkv_pot, "-y"]

            for stevilka in ohrani:
                ukaz.extend(["-map", f"0:{stevilka}"])

            izhodna_zacasna_pot = self._nova_zacasna_mkv_pot(
                ciljna_pot, "output"
            )
            ukaz.extend(["-c", "copy", izhodna_zacasna_pot])

            self._izvedi_ukaz_z_osvezevanjem(ukaz)
            os.replace(izhodna_zacasna_pot, ciljna_pot)
            izhodna_zacasna_pot = None
            self._nastavi_prosto("Sledi odstranjene.")
            messagebox.showinfo(
                "Uspeh", f"Sledi uspešno odstranjene!\n\nShranjeno v:\n{ciljna_pot}"
            )
        except (
            subprocess.CalledProcessError,
            OperacijaPrekinjena,
            OSError,
            RuntimeError,
        ) as e:
            if self._zapiranje:
                self._nastavi_prosto("Operacija prekinjena.")
                return
            self._nastavi_prosto("Napaka pri odstranjevanju.")
            messagebox.showerror(
                "Napaka",
                f"Napaka pri odstranjevanju:\n{self._opis_napake_procesa(e)}",
            )
        finally:
            self._varno_odstrani(izhodna_zacasna_pot)


def hitro_pretvorba_cli(izbrisi_izvorne=False):
    """CLI način za hitro pretvorbo vseh video datotek v trenutnem imeniku."""

    # Poišči orodja
    def poisci_orodje(ime):
        pot = shutil.which(ime)
        if pot:
            return pot
        try:
            rezultat = subprocess.run(
                ["flatpak", "list", "--app", "--columns=application"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if rezultat.returncode == 0:
                aplikacije = rezultat.stdout.strip().split("\n")
                if ime in ["ffmpeg", "ffprobe"]:
                    for app in aplikacije:
                        if "ffmpeg" in app.lower():
                            return f"flatpak run --command={ime} {app}"
                if ime == "mkvmerge":
                    for app in aplikacije:
                        if "mkvtoolnix" in app.lower():
                            return f"flatpak run --command=mkvmerge {app}"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    ffmpeg = poisci_orodje("ffmpeg")
    ffprobe = poisci_orodje("ffprobe")
    mkvmerge = poisci_orodje("mkvmerge")

    if not mkvmerge:
        print("Napaka: mkvmerge ni nameščen.")
        sys.exit(1)
    if not ffmpeg or not ffprobe:
        print("Napaka: za -q sta potrebna ffmpeg in ffprobe.")
        sys.exit(1)

    # Poišči video datoteke rekurzivno
    video_koncnice = [
        ".mp4",
        ".avi",
        ".mov",
        ".wmv",
        ".flv",
        ".webm",
        ".m4v",
        ".mpeg",
        ".mpg",
    ]
    trenutni_dir = os.getcwd()

    video_datoteke = []
    mkv_datoteke = []
    for root, dirs, files in os.walk(trenutni_dir):
        for datoteka in files:
            pot = os.path.join(root, datoteka)
            koncnica = Path(datoteka).suffix.lower()
            if koncnica in video_koncnice:
                video_datoteke.append(pot)
            elif koncnica == ".mkv":
                mkv_datoteke.append(pot)

    if not video_datoteke and not mkv_datoteke:
        print("Ni video datotek v trenutnem imeniku ali podmapah.")
        sys.exit(0)

    if video_datoteke:
        print(f"Najdenih {len(video_datoteke)} video datotek (rekurzivno).")
    if mkv_datoteke:
        print(f"Najdenih {len(mkv_datoteke)} MKV datotek za preverjanje (rekurzivno).")

    uspesne = 0
    neuspesne = 0

    # Jeziki, ki jih štejemo kot "naše" podnapise (prioriteta: slv > hrv > srp > bos)
    nasi_jeziki = ["slv", "sl", "hrv", "hr", "srp", "sr", "bos", "bs"]
    prioriteta_jezikov = {
        "slv": 0,
        "sl": 0,
        "hrv": 1,
        "hr": 1,
        "srp": 2,
        "sr": 2,
        "bos": 3,
        "bs": 3,
    }
    angleski_audio_jeziki = {"eng", "en", "english"}

    def je_angleski_audio(sled):
        jezik = sled.get("tags", {}).get("language", "").lower()
        return (
            jezik in angleski_audio_jeziki
            or jezik.startswith("en-")
            or jezik.startswith("eng-")
        )

    def izberi_audio_sled(sledi):
        """Vrne (kodek, globalni indeks, audio-relativni indeks), z angleščino prednostno."""
        audio_sledi = []
        for sled in sledi:
            if sled.get("codec_type") == "audio":
                audio_sledi.append((sled, len(audio_sledi)))

        if not audio_sledi:
            return None, None, None

        izbrana_sled, relativni_indeks = next(
            (
                (sled, relativni_indeks)
                for sled, relativni_indeks in audio_sledi
                if je_angleski_audio(sled)
            ),
            audio_sledi[0],
        )
        return (
            izbrana_sled.get("codec_name"),
            izbrana_sled.get("index"),
            relativni_indeks,
        )

    def edinstvena_bac_pot(pot):
        osnovna_pot = Path(pot)
        kandidat = osnovna_pot.with_name(f"{osnovna_pot.stem}_bac{osnovna_pot.suffix}")
        stevec = 2
        while kandidat.exists():
            kandidat = osnovna_pot.with_name(
                f"{osnovna_pot.stem}_bac_{stevec}{osnovna_pot.suffix}"
            )
            stevec += 1
        return str(kandidat)

    def je_srbska_latinica(sled):
        """Ali subtitle sled nedvoumno označuje srbsko latinico."""
        oznake = sled.get("tags", {})
        jezik = oznake.get("language", "").lower().replace("_", "-")
        naslov = oznake.get("title", "").lower()
        return (
            jezik in {"sr-latn", "srp-latn", "sr-latin", "srp-latin"}
            or "latin" in naslov
            or "latinica" in naslov
        )

    def izberi_podnapis(sledi):
        """Vrne (relativni indeks, jezik) za edini ohranjeni podnapis."""
        kandidati = []
        sub_indeks = 0
        for sled in sledi:
            if sled.get("codec_type") != "subtitle":
                continue
            jezik = sled.get("tags", {}).get("language", "").lower()
            if jezik in {"slv", "sl"}:
                kandidati.append((0, sub_indeks, jezik))
            elif jezik in {"hrv", "hr"}:
                kandidati.append((1, sub_indeks, jezik))
            elif jezik in {"bos", "bs"}:
                kandidati.append((2, sub_indeks, jezik))
            elif je_srbska_latinica(sled):
                kandidati.append((3, sub_indeks, jezik or "srp-Latn"))
            sub_indeks += 1
        if not kandidati:
            return None, None
        _, indeks, jezik = min(kandidati)
        return indeks, jezik

    def je_mkv_ze_pripravljen(sledi, zunanji_srt):
        """Preveri, ali bi bila ponovna obdelava datoteke brez učinka."""
        if zunanji_srt:
            return False

        zvoki = [sled for sled in sledi if sled.get("codec_type") == "audio"]
        podnapisi = [sled for sled in sledi if sled.get("codec_type") == "subtitle"]
        if len(zvoki) != 1:
            return False

        zvok = zvoki[0]
        if zvok.get("codec_name", "").lower() != "ac3":
            return False
        if not zvok.get("disposition", {}).get("default", 0):
            return False

        pod_relativni, _ = izberi_podnapis(sledi)
        if pod_relativni is None:
            return not podnapisi
        if len(podnapisi) != 1:
            return False
        return bool(podnapisi[0].get("disposition", {}).get("default", 0))

    def pridobi_sledi(pot):
        if not ffprobe:
            raise RuntimeError("ffprobe ni nameščen; -q ne more varno izbrati sledi.")
        ukaz = (
            ffprobe.split()
            if "flatpak run" in ffprobe
            else [ffprobe]
        ) + ["-v", "error", "-print_format", "json", "-show_streams", pot]
        rezultat = subprocess.run(ukaz, capture_output=True, text=True, check=True)
        return json.loads(rezultat.stdout).get("streams", [])

    def pridobi_mkvmerge_track_map(pot, ffprobe_sledi):
        """Preslika FFprobe stream indekse v mkvmerge track ID-je za CLI."""
        ukaz = (
            mkvmerge.split()
            if "flatpak run" in mkvmerge
            else [mkvmerge]
        ) + ["-J", pot]
        rezultat = subprocess.run(ukaz, capture_output=True, text=True, check=True)
        podatki = json.loads(rezultat.stdout)
        mkv_vrste = {"video": "video", "audio": "audio", "subtitles": "subtitle"}
        mkv_po_vrsti = {"video": [], "audio": [], "subtitle": []}
        for sled in podatki.get("tracks", []):
            vrsta = mkv_vrste.get(sled.get("type"))
            if vrsta in mkv_po_vrsti:
                mkv_po_vrsti[vrsta].append(str(sled["id"]))

        ff_po_vrsti = {"video": [], "audio": [], "subtitle": []}
        for sled in ffprobe_sledi:
            vrsta = sled.get("codec_type")
            if vrsta in ff_po_vrsti:
                ff_po_vrsti[vrsta].append(str(sled["index"]))

        preslikava = {}
        for vrsta in ff_po_vrsti:
            for ffprobe_id, mkvmerge_id in zip(
                ff_po_vrsti[vrsta], mkv_po_vrsti[vrsta]
            ):
                preslikava[ffprobe_id] = mkvmerge_id
        return preslikava

    def obdelaj_mkv_po_pravilih(mkv_pot, srt_pot, izbrisi_izvorne):
        """Ohrani video, en angleški zvok in en prednostni podnapis."""
        try:
            sledi = pridobi_sledi(mkv_pot)
            audio_kodek, _, audio_relativni = izberi_audio_sled(sledi)
            if audio_relativni is None:
                raise RuntimeError("MKV nima zvočne sledi.")

            # Zunanji SRT je slovenski in ima zato prednost pred vdelanimi sledmi.
            sub_relativni, sub_jezik = izberi_podnapis(sledi)
            uporabi_zunanji_srt = bool(srt_pot)
            if uporabi_zunanji_srt:
                sub_relativni, sub_jezik = None, "slv"

            if je_mkv_ze_pripravljen(sledi, uporabi_zunanji_srt):
                ciljna_pot = (
                    mkv_pot
                    if izbrisi_izvorne
                    else edinstvena_bac_pot(mkv_pot)
                )
                if izbrisi_izvorne:
                    print("  = že pravilno urejen; preskakujem ponovno obdelavo")
                else:
                    shutil.copy2(mkv_pot, ciljna_pot)
                    print(f"  = že pravilno urejen; kopija: {Path(ciljna_pot).name}")
                return True

            pretvori_audio = audio_kodek and audio_kodek.lower() != "ac3"
            ciljna_pot = mkv_pot if izbrisi_izvorne else edinstvena_bac_pot(mkv_pot)
            zacasna_pot = str(
                Path(ciljna_pot).with_name(f".{Path(ciljna_pot).stem}.bac.tmp.mkv")
            )
            print(f"Obdelujem: {Path(mkv_pot).name}")
            print("  + video kopiram brez pretvarjanja")
            print(
                "  + zvok: angleški" if je_angleski_audio(
                    [sled for sled in sledi if sled.get("codec_type") == "audio"][audio_relativni]
                ) else "  + angleškega zvoka ni; ohranjam prvo zvočno sled"
            )
            if pretvori_audio:
                print(f"  + pretvarjam zvok ({audio_kodek} → AC3)")
            if uporabi_zunanji_srt:
                print(f"  + ohranjam slovenske podnapise: {Path(srt_pot).name}")
            elif sub_relativni is not None:
                print(f"  + ohranjam podnapise: {sub_jezik}")
            else:
                print("  + odstranjujem vse podnapise (ni slv/hrv/bos/srbskih latinica)")

            ukaz = (ffmpeg.split() if "flatpak run" in ffmpeg else [ffmpeg])
            ukaz.extend(["-y", "-i", mkv_pot])
            if uporabi_zunanji_srt:
                ukaz.extend(["-i", srt_pot])
            ukaz.extend(["-map", "0:v?", "-map", f"0:a:{audio_relativni}"])
            if uporabi_zunanji_srt:
                ukaz.extend(["-map", "1:0", "-metadata:s:s:0", "language=slv"])
            elif sub_relativni is not None:
                ukaz.extend(["-map", f"0:s:{sub_relativni}"])
            # Ohrani tudi priponke in podatkovne sledi, brez vključitve drugih podnapisov.
            ukaz.extend(["-map", "0:t?", "-map", "0:d?", "-c:v", "copy", "-c:s", "copy"])
            if pretvori_audio:
                ukaz.extend(["-c:a", "ac3", "-b:a", "192k"])
            else:
                ukaz.extend(["-c:a", "copy"])
            ukaz.extend(["-disposition:a:0", "default"])
            if uporabi_zunanji_srt or sub_relativni is not None:
                ukaz.extend(["-disposition:s:0", "default"])
            ukaz.append(zacasna_pot)
            subprocess.run(ukaz, check=True, capture_output=True)

            os.replace(zacasna_pot, ciljna_pot)
            print(f"  ✓ {'Posodobljen' if izbrisi_izvorne else 'Ustvarjen'}: {Path(ciljna_pot).name}")
            if izbrisi_izvorne and srt_pot:
                os.remove(srt_pot)
                print(f"  ✗ Izbrisan: {Path(srt_pot).name}")
            return True
        except (RuntimeError, subprocess.CalledProcessError, OSError) as e:
            print(f"  ✗ Napaka: {str(e)[:300]}")
            if "zacasna_pot" in locals() and os.path.exists(zacasna_pot):
                os.remove(zacasna_pot)
            return False

    # Najprej obdelaj obstoječe MKV datoteke
    for mkv_pot in mkv_datoteke:
        osnovni_ime = Path(mkv_pot).stem
        video_dir = os.path.dirname(mkv_pot)

        # Poišči pripadajoči SRT v isti mapi
        srt_pot = None
        for koncnica in [".srt", ".sl.srt", ".slv.srt", "_sl.srt", "_slv.srt"]:
            mozna_pot = os.path.join(video_dir, f"{osnovni_ime}{koncnica}")
            if os.path.exists(mozna_pot):
                srt_pot = mozna_pot
                break

        if not srt_pot:
            for datoteka in os.listdir(video_dir):
                if datoteka.lower().endswith(".srt"):
                    dat_stem = Path(datoteka).stem
                    if (
                        dat_stem == osnovni_ime
                        or dat_stem.startswith(osnovni_ime + ".")
                        or dat_stem.startswith(osnovni_ime + "_")
                    ):
                        srt_pot = os.path.join(video_dir, datoteka)
                        break

        if obdelaj_mkv_po_pravilih(mkv_pot, srt_pot, izbrisi_izvorne):
            uspesne += 1
        else:
            neuspesne += 1

    for video_pot in video_datoteke:
        osnovni_ime = Path(video_pot).stem
        video_dir = os.path.dirname(video_pot)
        ciljna_pot = os.path.join(video_dir, f"{osnovni_ime}.mkv")

        # Če MKV že obstaja, preskoči (že obdelano zgoraj)
        if os.path.exists(ciljna_pot):
            continue

        # Poišči pripadajoči SRT v isti mapi
        srt_pot = None
        for koncnica in [".srt", ".sl.srt", ".slv.srt", "_sl.srt", "_slv.srt"]:
            mozna_pot = os.path.join(video_dir, f"{osnovni_ime}{koncnica}")
            if os.path.exists(mozna_pot):
                srt_pot = mozna_pot
                break

        # Poskusi najti SRT z enakim začetkom imena
        if not srt_pot:
            for datoteka in os.listdir(video_dir):
                if datoteka.lower().endswith(".srt"):
                    dat_stem = Path(datoteka).stem
                    if (
                        dat_stem == osnovni_ime
                        or dat_stem.startswith(osnovni_ime + ".")
                        or dat_stem.startswith(osnovni_ime + "_")
                    ):
                        srt_pot = os.path.join(video_dir, datoteka)
                        break

        print(f"Pretvarjam: {Path(video_pot).name}")
        if srt_pot:
            print(f"  + podnapisi: {Path(srt_pot).name}")

        try:
            # Preveri audio kodek in poišči indeks prvega audio streama
            audio_kodek = None
            izbrani_audio_id = None
            izbrani_audio_relativni = None
            ffprobe_sledi = []
            if ffprobe:
                try:
                    if "flatpak run" in ffprobe:
                        deli = ffprobe.split()
                        ukaz = deli + [
                            "-v",
                            "quiet",
                            "-print_format",
                            "json",
                            "-show_streams",
                            video_pot,
                        ]
                    else:
                        ukaz = [
                            ffprobe,
                            "-v",
                            "quiet",
                            "-print_format",
                            "json",
                            "-show_streams",
                            video_pot,
                        ]
                    rezultat = subprocess.run(
                        ukaz, capture_output=True, text=True, check=True
                    )
                    podatki = json.loads(rezultat.stdout)
                    ffprobe_sledi = podatki.get("streams", [])
                    audio_kodek, izbrani_audio_id, izbrani_audio_relativni = (
                        izberi_audio_sled(ffprobe_sledi)
                    )
                except Exception:
                    pass

            potrebna_pretvorba_audio = audio_kodek and audio_kodek.lower() not in [
                "ac3"
            ]
            vhodna_datoteka = video_pot
            zacasna_pot = None
            izhodna_zacasna_pot = None
            mkv_audio_id = None
            neposredno_izhod = False
            if not potrebna_pretvorba_audio and izbrani_audio_id is not None:
                mkv_audio_map = pridobi_mkvmerge_track_map(video_pot, ffprobe_sledi)
                mkv_audio_id = mkv_audio_map.get(str(izbrani_audio_id))
                if mkv_audio_id is None:
                    raise RuntimeError(
                        "Izbrane zvočne sledi ni mogoče zanesljivo najti v mkvmerge."
                    )

            # Če je potrebna pretvorba zvoka, naredimo celoten izhod z enim
            # ffmpeg prehodom. Prejšnja pot je najprej ustvarila začasni MKV,
            # nato pa ga je še enkrat prepakiral mkvmerge.
            if potrebna_pretvorba_audio and ffmpeg:
                print(f"  Pretvarjam zvok ({audio_kodek} → AC3)...")
                fd, izhodna_zacasna_pot = tempfile.mkstemp(
                    prefix=f".{Path(ciljna_pot).stem}.bac-output-",
                    suffix=".mkv",
                    dir=video_dir,
                )
                os.close(fd)
                os.remove(izhodna_zacasna_pot)

                if "flatpak run" in ffmpeg:
                    ukaz_ff = ffmpeg.split() + ["-nostdin", "-y", "-i", video_pot]
                else:
                    ukaz_ff = [ffmpeg, "-nostdin", "-y", "-i", video_pot]

                if srt_pot:
                    ukaz_ff.extend(["-i", srt_pot])

                audio_map = (
                    f"0:a:{izbrani_audio_relativni}"
                    if izbrani_audio_relativni is not None
                    else "0:a:0"
                )
                ukaz_ff.extend(["-map", "0:v", "-map", audio_map])
                if srt_pot:
                    ukaz_ff.extend(
                        [
                            "-map",
                            "1:0",
                            "-metadata:s:s:0",
                            "language=slv",
                            "-disposition:s:0",
                            "default",
                        ]
                    )
                ukaz_ff.extend(
                    [
                        "-map_metadata",
                        "0",
                        "-c:v",
                        "copy",
                        "-c:a",
                        "ac3",
                        "-b:a",
                        "192k",
                        "-c:s",
                        "copy",
                        "-disposition:a:0",
                        "default",
                        izhodna_zacasna_pot,
                    ]
                )

                subprocess.run(ukaz_ff, check=True, capture_output=True)
                os.replace(izhodna_zacasna_pot, ciljna_pot)
                izhodna_zacasna_pot = None
                neposredno_izhod = True

            if not neposredno_izhod:
                # Združi z mkvmerge, kadar zvoka ni treba pretvarjati.
                fd, izhodna_zacasna_pot = tempfile.mkstemp(
                    prefix=f".{Path(ciljna_pot).stem}.bac-output-",
                    suffix=".mkv",
                    dir=video_dir,
                )
                os.close(fd)
                os.remove(izhodna_zacasna_pot)
                if "flatpak run" in mkvmerge:
                    ukaz = mkvmerge.split() + ["-o", izhodna_zacasna_pot]
                else:
                    ukaz = [mkvmerge, "-o", izhodna_zacasna_pot]

                # Ohrani samo izbrano zvočno sled iz izvorne datoteke.
                if mkv_audio_id is not None:
                    ukaz.extend(["--audio-tracks", str(mkv_audio_id)])
                ukaz.append(vhodna_datoteka)

                if srt_pot:
                    ukaz.extend(["--language", "0:slv", "--default-track", "0:yes"])
                    ukaz.append(srt_pot)

                subprocess.run(ukaz, check=True, capture_output=True)
                os.replace(izhodna_zacasna_pot, ciljna_pot)
                izhodna_zacasna_pot = None

            # Počisti začasne datoteke
            if zacasna_pot and os.path.exists(zacasna_pot):
                os.remove(zacasna_pot)

            print(f"  ✓ Ustvarjen: {Path(ciljna_pot).name}")
            uspesne += 1

            # Izbriši izvorne datoteke če je zahtevano
            if izbrisi_izvorne:
                os.remove(video_pot)
                print(f"  ✗ Izbrisan: {Path(video_pot).name}")
                if srt_pot:
                    os.remove(srt_pot)
                    print(f"  ✗ Izbrisan: {Path(srt_pot).name}")

        except (subprocess.CalledProcessError, OSError, RuntimeError) as e:
            stderr = getattr(e, "stderr", None)
            napaka = stderr.decode() if isinstance(stderr, bytes) else (stderr or str(e))
            print(f"  ✗ Napaka: {napaka[:100]}")
            neuspesne += 1
            # Počisti morebitne začasne datoteke
            if zacasna_pot and os.path.exists(zacasna_pot):
                os.remove(zacasna_pot)
            if izhodna_zacasna_pot and os.path.exists(izhodna_zacasna_pot):
                os.remove(izhodna_zacasna_pot)

    print(f"\nKončano: {uspesne} uspešnih, {neuspesne} neuspešnih")


def main():
    # Parsiraj argumente
    class SloveneHelpFormatter(argparse.RawDescriptionHelpFormatter):
        def format_help(self):
            help_text = super().format_help()
            help_text = help_text.replace("usage:", "Uporaba:")
            help_text = help_text.replace("options:", "Opcije:")
            help_text = help_text.replace("optional arguments:", "Opcije:")
            help_text = help_text.replace(
                "positional arguments:", "Pozicijski argumenti:"
            )
            return help_text

    parser = argparse.ArgumentParser(
        description=f"baC {verzija} - Orodje za urejanje MKV datotek",
        formatter_class=SloveneHelpFormatter,
        epilog="""
Primeri:
  bac           Zaženi grafični vmesnik
  bac film.mkv  Zaženi grafični vmesnik in odpri datoteko
  bac -q        Uredi MKV: en zvok in en prednostni podnapis
  bac -qq       Kot -q, ampak zamenja izvorne datoteke
        """,
        add_help=False,
    )
    parser.add_argument(
        "-h", "--help", action="help", help="Prikaži to sporočilo o pomoči in izstopi."
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"baC {verzija}",
        help="Prikaži verzijo in izstopi.",
    )
    parser.add_argument(
        "-q",
        "--quick",
        action="count",
        default=0,
        help="Uredi MKV (-q ustvari _bac, -qq zamenja izvorno datoteko)",
    )
    tema_skupina = parser.add_mutually_exclusive_group()
    tema_skupina.add_argument(
        "--light", action="store_true", help="Uporabi svetlo temo"
    )
    tema_skupina.add_argument("--dark", action="store_true", help="Uporabi temno temo")
    parser.add_argument(
        "datoteke",
        nargs="*",
        help="Datoteka za odpiranje v GUI načinu (podprti so tudi file:// URI iz .desktop %%U)",
    )

    args = parser.parse_args()

    if args.quick > 0:
        # CLI način
        izbrisi = args.quick >= 2
        hitro_pretvorba_cli(izbrisi_izvorne=izbrisi)
    else:
        # GUI način
        # Določi temo
        prisiljena_tema = None
        if args.light:
            prisiljena_tema = "svetla"
        elif args.dark:
            prisiljena_tema = "temna"

        tkinter_dnd = _pripravi_tkinterdnd2()
        root = tkinter_dnd.Tk() if tkinter_dnd is not None else tk.Tk()

        app = BaMKV(root, prisiljena_tema=prisiljena_tema, zacetne_datoteke=args.datoteke)
        root.mainloop()


if __name__ == "__main__":
    main()
