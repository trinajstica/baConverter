# baC 🔧

`baC` (skripta `bac.py`, ukaz `bac`) je orodje za urejanje in združevanje MKV datotek. Ponuja grafični vmesnik za urejanje MKV in uporabno ukazno vrstico za hitro obdelavo video vsebin v trenutnem imeniku.

## Funkcije ✅

- Dodajanje podnapisov v MKV
- Nastavljanje privzetih podnapisov
- Dodajanje in/ali pretvorba zvočnih sledov (v AAC) po potrebi
- Združevanje videa in podnapisov v `.mkv`
- Podpora za povleci in spusti v GUI (če so na voljo dodatki)
- Hiter CLI način za obdelavo trenutnega imenika

## Zahteve ⚙️

- Python 3
- `mkvmerge` (MKVToolNix) — obvezno za združevanje in CLI
- `ffmpeg` in `ffprobe` — priporočeno za pretvorbe in prepoznavo kodakov
- `python3-tk` (tkinter) — za GUI
- opcijsko: `tkinterdnd2>=0.4.4` ali `tkdnd` za povleci in spusti v GUI

Če `tkinterdnd2` ob zagonu ni nameščen, baC vpraša za samodejno namestitev
paketa prek trenutnega Pythona. Če namestitev zavrnete ali ne uspe, lahko
datoteke še vedno odpirate z gumbom »Odpri MKV«.

### Namestitev (primer: Debian/Ubuntu)

```bash
sudo apt update
sudo apt install -y ffmpeg mkvtoolnix python3-tk
python3 -m pip install --user "tkinterdnd2>=0.4.4"
```

### Namestitev (primer: Solus)

```bash
sudo eopkg install -y ffmpeg mkvtoolnix python3-tkinter
python3 -m pip install --user "tkinterdnd2>=0.4.4"
```

Za uporabnike Flatpak-a (opcijsko):

```bash
flatpak install flathub org.ffmpeg.FFmpeg
flatpak install flathub org.bunkus.mkvtoolnix
```

Za lažji ukaz iz terminala (po želji):

```bash
chmod +x bac.py
sudo ln -s $(pwd)/bac.py /usr/local/bin/bac
```

## Uporaba

### GUI

- Zaženi: `python3 bac.py` ali `bac` (če je nameščen).
- V GUI odpri MKV datoteko, dodaj podnapise ali zvočne datoteke (gumb ali povleci in spusti), nastavi jezik/privzeto sled in zaženi obdelavo.

### CLI

Hiter način za obdelavo trenutnega imenika:

- `python3 bac.py -q`  — za vsak MKV ustvari kopijo `_bac`: video ostane nespremenjen, ostane en angleški zvočni zapis (če ga ni, prvi), podnapisi pa so samo slovenski, sicer hrvaški, sicer bosanski, sicer srbski v latinici. Edini ohranjeni podnapisi so privzeti.
- `python3 bac.py -qq` — kot zgoraj, vendar po uspehu zamenja izvorni MKV.

CLI način preskoči MKV datoteke, ki so že pravilno urejene. Pri vhodnih video
datotekah, katerih zvok ni AC3, se video in zvok pretvorita v enem prehodu
`ffmpeg`, zato ni več vmesnega prepakiranja z `mkvmerge`.

#### Pravila za podnapise in zvok

Za datoteko `film.mkv` baC preveri samo natančno poimenovano zunanjo datoteko
`film.srt` v isti mapi.

- Če `film.srt` obstaja, ima vedno prednost pred vsemi notranjimi podnapisi,
  ne glede na njihove jezikovne oznake. Zunanji SRT se združi z MKV kot edini
  podnapis, vsi notranji podnapisi pa se odstranijo. Pri `-qq` se uporabljeni
  zunanji `film.srt` po uspešni obdelavi izbriše.
- Datoteke z drugačnimi priponami ali dodatnimi oznakami, na primer
  `film.sl.srt`, `film.en.srt` ali `film.forced.srt`, se ne obravnavajo kot
  zunanji SRT za ta namen.
- Če `film.srt` ne obstaja, se notranji podnapisi obdelajo po običajnih
  pravilih: prednost ima `slv`/`sl`, nato `hrv`/`hr`, nato `bos`/`bs`, nato
  srbski podnapis, označen kot latinica. Izbran ostane samo najbolj prednostni
  podnapis in je nastavljen kot privzet. Če ustreznega podnapisa ni, se vsi
  notranji podnapisi odstranijo.
- Ne glede na zunanji SRT se preveri tudi zvok: izbere se angleška zvočna sled,
  če obstaja, sicer prva. Če ni v formatu AC3, se pretvori v AC3 in nastavi kot
  privzeta zvočna sled.

Pri `-q` se ustvari kopija z dodatkom `_bac`, pri `-qq` pa se po uspešni
obdelavi zamenja izvorni MKV.

## Galerija slik 🖼️

Kliknite na sličico za ogled v polni velikosti. (Klik odpre sliko v novi kartici.)

<table>
<tr>
<td align="center">
<a href="slike/slika1.png" target="_blank"><img src="slike/slika1.png" alt="slika1" width="200" /></a>
</td>
<td align="center">
<a href="slike/slika2.png" target="_blank"><img src="slike/slika2.png" alt="slika2" width="200" /></a>
</td>
<td align="center">
<a href="slike/slika3.png" target="_blank"><img src="slike/slika3.png" alt="slika3" width="200" /></a>
</td>
</tr>
<tr>
<td align="center">
<a href="slike/slika4.png" target="_blank"><img src="slike/slika4.png" alt="slika4" width="200" /></a>
</td>
<td align="center">
<a href="slike/slika5.png" target="_blank"><img src="slike/slika5.png" alt="slika5" width="200" /></a>
</td>
<td align="center">
<a href="slike/slika6.png" target="_blank"><img src="slike/slika6.png" alt="slika6" width="200" /></a>
</td>
</tr>
</table>

## Pogoste težave ❗

> Če program opozori, da manjkajo orodja, namestite `ffmpeg` in `mkvtoolnix`. CLI zahteva `mkvmerge` in se bo ustavil, če ga ni.

## Licenca

Projekt je licenciran pod MIT licenco. Glej `LICENSE`.
