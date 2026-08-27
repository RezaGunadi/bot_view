# 🎬 Playlist Studio

Player playlist video lokal untuk **YouTube / TikTok / Facebook / Instagram**, dengan
**banyak playlist**, **banyak stream berbarengan** (tiap anak satu window di monitor
masing-masing), dan **database SQLite yang bikin dirinya sendiri** saat runner dijalankan.

Tiap video diputar sebagai player/embed **baru** dan URL aslinya dicatat sebagai satu
*hit* — jadi bukan satu iframe playlist YouTube yang jalan sendiri di dalam.

---

> Butuh contekan perintah cepat (Windows maupun Lubuntu)? Buka **`guide.txt`**.

## Jalankan

```bash
python run.py
```

Satu perintah, itu saja — atau klik dua kali `start.bat` di Windows. Runner mengurus
semuanya sendiri, tiap langkah otomatis dilewati kalau sudah beres:

1. **Dependency** — cek `fastapi` / `uvicorn` / `python-dotenv`, install **hanya yang
   kurang**. Run berikutnya: `[deps] 3 dependency sudah terpasang — skip.`
2. **Database** — kalau `data/playlist.db` belum ada, dibuat lengkap dengan tabelnya;
   kalau versinya sudah terkini: `[db] Skema sudah v1 ... skip.`
3. Deteksi browser (Chrome → Edge → Brave → Firefox) + **enumerasi monitor** yang terpasang.
4. Jalankan server di `127.0.0.1:8000` dan buka GUI.

```bash
python run.py --no-browser     # tanpa buka GUI otomatis
python run.py --port 8123      # ganti port
python run.py --migrate-only   # cuma siapkan database
python run.py --reset-db       # backup db lama (.db.bak) lalu bikin ulang
python run.py --skip-deps      # lewati pengecekan dependency
python run.py --install-autostart   # jalan sendiri tiap Windows login
python run.py --remove-autostart
python run.py --reload         # auto-reload saat ngoding
```

---

## Pindah ke komputer lain

### Cara A — exe portable (komputer anak tidak perlu Python sama sekali)

Sekali saja di komputermu:

```bash
python build_exe.py
```

Hasilnya `dist/PlaylistStudio.exe` (~21 MB). **Copy satu file itu** ke komputer anak,
klik dua kali, selesai. Python, FastAPI, dan seluruh GUI sudah ada di dalamnya.
Folder `data/` (database + profil browser) dibuat otomatis di sebelah exe-nya, jadi
taruh exe-nya di folder sendiri, jangan di Desktop yang berantakan.

Satu-satunya yang masih perlu ada di komputer anak: **Chrome, Edge, Brave, atau Firefox**,
itu pun hanya supaya window-nya terisolasi dan bisa ditempatkan per monitor.

### Cara B — copy source (Windows/Mac)

Copy seluruh folder ini, lalu di sana `python run.py`. Butuh **Python 3.10 atau lebih baru**
— versi stabil terbaru pun aman, karena dependency-nya dipasang dengan batas bawah
(`fastapi>=0.115`) bukan versi terkunci. Saat install di Windows centang
**"Add Python to PATH"**. Perlu internet sekali di run pertama untuk memasang 3 dependency.

Yang **tidak perlu** ikut dicopy: `data/`, `__pycache__/`, `.venv/`, `build/`, `dist/`.
Kalau `data/playlist.db` ikut dicopy, playlist-mu ikut pindah; kalau tidak, komputer itu
mulai dari kosong.

### Cara C — Lubuntu / Linux

Jalan di Linux juga, dan untuk mini PC berspek kecil ini pilihan bagus.

```bash
sudo apt install python3 chromium-browser wmctrl    # firefox juga boleh
python3 run.py
```

| Paket | Untuk apa | Wajib? |
|---|---|---|
| `python3` | Sudah ada bawaan Lubuntu (3.10+ sejak 22.04). | Ya |
| `chromium-browser` atau `firefox` | Window stream terisolasi. | Ya |
| `wmctrl` | Menempatkan window ke monitor yang benar. | Sangat disarankan |
| `xrandr` | Mendeteksi daftar monitor. Sudah ada bawaan. | Ya |

**Penting: pilih sesi X11, bukan Wayland.** Deteksi monitor (`xrandr`) dan penempatan
window (`wmctrl`) bekerja lewat X11. Lubuntu dengan LXQt memakai X11 secara bawaan, jadi
biasanya tidak perlu diapa-apakan — tapi kalau nanti kamu ganti ke sesi Wayland, semua
stream akan menumpuk di satu monitor.

Autostart pakai XDG (dihormati LXQt, XFCE, GNOME, KDE):

```bash
python3 run.py --install-autostart    # bikin ~/.config/autostart/playliststudio.desktop
python3 run.py --remove-autostart
```

**Kalau mau versi exe di Linux**, `build_exe.py` harus dijalankan **di komputer Linux itu**
— PyInstaller tidak bisa membuat binary Linux dari Windows. Tapi untuk Linux sebetulnya
tidak perlu: `python3 run.py` sudah cukup karena Python-nya sudah ada.

#### Catatan spek kecil

Beban terberatnya bukan aplikasi ini, tapi **memutar video** di beberapa window sekaligus.
Yang benar-benar berpengaruh:

- **Ukuran window menentukan kualitas video.** YouTube memilih resolusi berdasarkan ukuran
  player. Window 1280x720 jauh lebih ringan daripada fullscreen 1080p, dan di layar ruangan
  anak-anak bedanya nyaris tidak terlihat. Kalau berat, jangan centang Fullscreen.
- **Pastikan akselerasi video aktif** — buka `chrome://gpu` di window stream dan lihat
  "Video Decode". Tanpa itu, decoding jatuh ke CPU dan mini PC akan megap-megap.
- Realistisnya, mini PC murah kuat 2-3 stream sekaligus. Lebih dari itu, turunkan ukuran
  window dulu sebelum menyalahkan aplikasinya.

## Cara pakai

1. **Bikin playlist** — kolom kiri, tombol `+ Baru`. Boleh sebanyak yang kamu mau.
2. **Isi playlist** — tempel link di kolom tengah. Video masuk *library* global, lalu
   ditautkan ke playlist yang sedang dibuka. Bisa diurutkan `↑ ↓`, atau `✕` untuk
   **hapus dari playlist ini saja** (video tetap ada di library & playlist lain).
3. **Copy playlist** — tombol `⧉ Copy`. Seluruh isi ikut tersalin; setelah itu kamu bisa
   buang beberapa video dari salinan tanpa mengubah yang asli.
4. **Bikin stream** — kolom kanan: nama (mis. `Anak 1`), playlist mana, **monitor mana**,
   urut/acak, timer, loop.
5. **Start** — `▶` di tiap stream, atau `▶ Start semua stream` untuk membuka semuanya
   sekaligus. Tiap stream = **satu window browser terpisah**, langsung muncul di monitor
   yang dipilih, jadi tinggal ditinggal atau digeser sesuka hati.

Kontrol di dalam window player: `Space` play/pause, `←` `→` prev/next, `f` fullscreen.

Yang memudahkan saat menyiapkan banyak playlist:

- **Banyak sekaligus** — tab di kotak tambah, tempel puluhan link sekali jalan (satu per
  baris). Link yang tidak dikenali ditinggal di kotak supaya bisa diperbaiki.
- **Dari Excel** — tab ketiga di kotak tambah. Lihat bagian di bawah.
- **Geser untuk mengurutkan** — tarik baris video ke posisi yang diinginkan.
- **Klik dua kali** judul video untuk mengubahnya, atau nama playlist untuk ganti nama.
- **Cari** — kotak pencarian menyaring isi playlist yang panjang.
- Semua pengaturan stream (playlist, monitor, urutan, timer, batas sesi) bisa diubah
  langsung di kartunya, termasuk saat stream sedang jalan.
- **Jadwal dibuat dalam satu form** — nama, jam mulai/selesai, dan hari (tombol
  Sen–Min, plus pintasan "Sen–Jum" / "Tiap hari") dalam satu layar. Klik baris jadwal
  untuk mengubahnya.
- Kartu stream yang sedang jalan menampilkan **judul video yang sedang diputar**,
  dilaporkan sendiri oleh window-nya.

## Menyusun playlist lewat Excel

Tab **Dari Excel** di kotak tambah (atau buka langsung `http://localhost:8000/#excel`).

1. **⬇ Download template** — file `.xlsx` berisi kolom yang benar, baris contoh, dan
   satu sheet **Petunjuk**.
2. Isi di Excel, simpan.
3. **⬆ Upload file terisi** — hasilnya dilaporkan per baris.

| Kolom | Wajib? | Isi |
|---|---|---|
| `url` | **Ya** | Link YouTube / TikTok / Facebook / Instagram |
| `playlist` | Tidak | Nama playlist tujuan. **Kalau belum ada, dibuat otomatis.** Kosong = masuk ke playlist yang sedang dibuka. |
| `judul` | Tidak | Kosongkan saja — tombol **Periksa** bisa mengambil judul aslinya |

Kolom `playlist` itu yang membuat fitur ini hemat waktu: **satu file bisa menyiapkan
semua ruangan sekaligus.** Contoh isi:

```
playlist       | url                                        | judul
Ruang Balita   | https://www.youtube.com/watch?v=...         | Lagu pembuka
Ruang Balita   | https://www.youtube.com/watch?v=...         |
Ruang Batita   | https://www.tiktok.com/@a/video/...         | Tarian
```

→ dua playlist dibuat, isinya langsung terisi.

Baris yang link-nya tidak dikenali **tidak menggagalkan seluruh impor** — sisanya tetap
masuk, dan yang bermasalah dilaporkan lengkap dengan nomor barisnya:

```
4 dari 5 baris masuk.
Playlist baru dibuat: Ruang Balita, Ruang Batita.
Gagal 1 baris:
  baris 5: link tidak dikenali — ini bukan link video
```

File `.csv` juga diterima (termasuk yang dipisah titik koma, seperti Excel di sebagian
pengaturan lokal).

## Jadwal otomatis

Panel **Jadwal otomatis** menyimpan preset jam: stream dinyalakan pada jam mulai dan
dimatikan pada jam selesai, pada hari-hari yang dipilih. Satu jadwal bisa berlaku untuk
**semua stream** atau untuk satu stream saja, jadi tiap ruangan boleh punya jam sendiri.

```
08:00 – 16:00  Jam sekolah        Sen–Jum · semua stream
13:00 – 15:30  Sesi sore Batita   Sen–Jum · Ruang Batita
```

Penjadwal bekerja berbasis **transisi**, bukan "pastikan selalu jalan": dia hanya
bertindak tepat saat jam mulai atau jam selesai terlewati. Jadi kalau kamu matikan sebuah
window secara manual di tengah jadwal, dia **tidak** dinyalakan ulang sendiri sampai
jadwal berikutnya — kontrol manual selalu menang.

Jadwal disimpan di database, jadi ikut pindah kalau `data/playlist.db` ikut dicopy.

## Kenapa tidak perlu diklik-klik

Tiap video diputar sebagai **player/embed yang benar-benar baru** — player sebelumnya
di-`destroy()`, elemennya dibuang, lalu dibuat lagi dengan videonya sendiri. Jadi
mekanismenya memang seperti membuka URL baru tiap ganti video, bukan satu iframe playlist
yang jalan sendiri di dalamnya.

Yang biasanya bikin harus ada orang mengklik, dan bagaimana ditangani:

| Kejadian | Yang terjadi sekarang |
|---|---|
| Autoplay diblokir browser | Window stream dibuka dengan flag autoplay diizinkan (Chrome) / `media.autoplay.default=0` (Firefox). |
| Video dihapus, private, atau dibatasi | Langsung dilewati ke video berikutnya. |
| Video tidak pernah mulai dalam 25 detik | Dilewati. |
| Video mandek di status "memuat" 45 detik | Dilewati. |
| **Semua** video gagal berturut-turut | Berhenti dengan pesan jelas, tidak berputar cepat tanpa henti. |
| Window browser crash / tertutup | Dibuka lagi otomatis (bisa dimatikan per stream). |
| Mini PC baru dinyalakan | Aplikasi ikut jalan kalau autostart dipasang. |
| Platform menjeda dan bertanya "masih menonton?" | **Tidak** dilanjutkan otomatis — lihat bawah. |

### Periksa playlist sebelum jam tayang

Tombol **✓ Periksa** di kolom tengah mengecek tiap video lewat endpoint oEmbed resmi
platform (tanpa API key, tanpa login):

- Video yang **dihapus / private / tidak bisa diputar** ditandai merah di daftar, jadi
  ketahuan pagi hari — bukan pas anak-anak sudah duduk di depan layar.
- **Judul asli terisi otomatis.** Tempel 30 link, tekan Periksa, daftarnya langsung
  berisi judul beneran alih-alih URL panjang.

Facebook dan Instagram butuh token aplikasi untuk dicek, jadi ditandai
"tidak bisa dicek" — bukan berarti rusak.

### Window mati sendiri → dibuka lagi

Tiap kartu stream punya **"Nyalakan lagi kalau mati sendiri"** (aktif secara bawaan).
Kalau window-nya hilang tanpa distop dari panel — browser crash, atau ada yang tidak
sengaja menutupnya — penjadwal membukanya lagi dalam ~30 detik, maksimal 5 kali per jam
supaya window yang rusak terus tidak dicoba tanpa henti.

Aturannya sederhana dan bisa diandalkan:

| Cara berhenti | Dinyalakan lagi? |
|---|---|
| Tombol **Stop** di panel | Tidak |
| Jam selesai di jadwal | Tidak |
| Ditutup pakai tombol **X** / browser crash | **Ya** |

Jadi kalau memang mau mematikan satu ruangan, pakai tombol Stop di panel — bukan
menutup window-nya.

### Nyala sendiri saat mini PC dihidupkan

```bash
python run.py --install-autostart     # atau: PlaylistStudio.exe --install-autostart
python run.py --remove-autostart
```

Membuat `PlaylistStudio.cmd` di folder Startup Windows. Mini PC dinyalakan → aplikasi
jalan → jadwal mengambil alih. Tidak ada yang perlu diklik sama sekali.

Jeda dari platform sengaja tidak dilawan. Itu mekanisme untuk memastikan ada penonton, dan
melanjutkannya otomatis sama saja memalsukan kehadiran orang. Yang aplikasi ini lakukan
adalah **melaporkannya** ke panel kontrol supaya kelihatan ruangan mana yang perlu didatangi.

### Angka `play_count` cuma menghitung yang beneran diputar

Video yang gagal diputar tetap tercatat di `play_log` sebagai percobaan, tapi
**tidak** menaikkan `play_count`. Angka itu baru naik setelah player melaporkan videonya
benar-benar mulai jalan, dan hanya sekali per percobaan.

## Kalau ada monitor mati

Stream **tidak pernah gagal** hanya karena monitornya hilang. Yang terjadi:

1. Window-nya dibuka di monitor yang masih ada — bukan error, bukan diam saja.
2. Kalau beberapa stream jatuh ke monitor yang sama, layarnya **dibagi jadi petak**
   supaya tidak ada yang tertimbun:

   ```
   2 window  ->  kiri | kanan
   4 window  ->  kiri-atas   kanan-atas
                 kiri-bawah  kanan-bawah
   ```

   Justru itu tujuannya: begitu lihat empat video berdesakan di satu layar, langsung
   ketahuan ada monitor yang mati. Kalau ditumpuk, yang kelihatan cuma satu dan
   yang lain hilang tanpa jejak.

3. Di panel kontrol muncul garis peringatan kuning di kartu stream-nya
   (`Monitor 3 tidak terdeteksi — dipakai Monitor 1`), dan dropdown Monitor tetap
   menampilkan **Monitor 3 (tidak terdeteksi)** — bukan diam-diam berganti jadi
   Monitor 1.

4. **Setelanmu tidak ditimpa.** Begitu monitornya nyala lagi, stream kembali ke sana
   dengan sendirinya. Panel memeriksa daftar monitor tiap 5 detik, dan ada tombol ↻
   di pojok kanan atas untuk memaksa deteksi ulang.

Kalau monitornya memang tidak akan dipasang lagi, tombol **⚠ Pindahkan** di kepala
panel Stream mengubah setelan itu secara permanen ke monitor yang ada.

Menutup salah satu window akan membuat sisanya melebar lagi mengisi ruang kosong.

### Kenapa window terpisah, bukan tab

Tiap stream dijalankan sebagai **proses browser sendiri** dengan `--user-data-dir`
terpisah (`--no-remote --new-instance` untuk Firefox). Itu yang membuat tiap ruangan
bisa ditaruh di monitor berbeda — tab dalam satu window tidak bisa dipisah ke layar
yang berbeda, dan hanya satu yang terlihat pada satu waktu.

## Melihat ruangan yang macet

Tiap window player mengirim kabar keadaannya ke server setiap 20 detik. Di kartu stream
muncul labelnya:

| Label | Artinya |
|---|---|
| `main` | Sedang memutar normal. |
| `terjeda` | Player berhenti — misalnya YouTube menampilkan konfirmasi "masih menonton?". Perlu diklik di ruangan itu. |
| `tidak merespons N mnt` | Sudah lama tidak ada kabar; window-nya mungkin ditutup atau halamannya bermasalah. |

Ini sengaja hanya **melaporkan**, bukan memancing player supaya terus jalan. Kalau sebuah
ruangan terjeda, itu memang perlu dilihat orang.

## Adil buat pemilik video

Aplikasi ini memutar embed resmi tiap platform, dari satu komputer, ditonton orang
sungguhan. Itu tayangan yang sah — dan buat pembuat videonya justru bagus.

Yang membuat tayangan jadi tidak sah bukan "banyak layar dari satu IP" — rumah, sekolah,
dan kantor memang begitu, dan platform sudah biasa menanganinya. Yang bermasalah adalah
memutar video **tanpa ada yang menonton** semata-mata supaya angkanya naik. Karena itu:

- **Jadwal otomatis** — atur jam nyala/mati sesuai jam operasional, supaya playlist tidak
  berputar semalaman di gedung kosong. Ini cara yang paling pas kalau video dibiarkan
  jalan seharian sebagai suasana ruangan.
- **Batas sesi (menit)** di tiap stream — alternatif kalau kamu mau window berhenti
  sendiri setelah sekian menit. `0` = tanpa batas.
- **Timer non-YouTube** jangan disetel terlalu pendek. Video yang cuma tampil beberapa
  detik lalu diganti tidak dihitung sebagai tontonan utuh, dan polanya persis seperti bot.
  Biarkan di 60 detik ke atas untuk TikTok/Reels.
- **Matikan "ulang dari awal"** kalau daftarnya pendek dan dipakai berjam-jam — lebih baik
  tambah variasi video daripada mengulang video yang sama berkali-kali.

Yang **tidak** disediakan aplikasi ini, dan memang disengaja:

- **IP berbeda per window, rotasi proxy, pemalsuan user-agent/fingerprint.** Semua window
  keluar lewat jalur yang sama dan terlihat apa adanya — satu tempat, banyak layar.
- **Auto-skip iklan.** Iklan itu justru bagian yang membayar pembuat videonya. Kalau iklan
  jadi masalah — misalnya isinya tidak pantas untuk anak — jalan yang benar adalah
  YouTube Premium (bebas iklan, pembuat video tetap dibayar dari uang langganan),
  YouTube Kids, atau konten berlisensi.
- **Melawan jeda otomatis.** Kalau platform menjeda karena tidak ada yang menyentuh layar,
  itu memang mekanisme untuk memastikan ada penonton. Aplikasi ini melaporkan keadaannya
  ke panel kontrol supaya bisa dicek orang, bukan menyimulasikan aktivitas.

---

## Privasi

| Yang dijaga | Caranya |
|---|---|
| Data tidak ke mana-mana | SQLite lokal di `data/playlist.db`. Tidak ada akun, tidak ada API key, tidak ada sinkronisasi. |
| Server tidak bisa diakses orang lain | Bind ke `127.0.0.1` saja. |
| Tontonan tidak nempel ke akun Google-mu | Tiap window stream jalan dengan `--user-data-dir` **sendiri** — profil kosong, tidak ada yang login. |
| Cookie/history tidak menumpuk | Profil stream **dihapus otomatis** saat distop dari GUI **maupun** saat window ditutup manual lewat tombol X (`WIPE_PROFILE_ON_STOP=1`). |
| Trafik bisa lewat VPN/proxy | Isi `PROXY_SERVER` di `.env` — semua window stream lewat situ, browser harianmu tidak ikut. |
| Embed YouTube tanpa cookie tracking | Pakai domain `youtube-nocookie.com`. |
| Referrer dibatasi | Hanya origin (`http://127.0.0.1:port`) yang dikirim, tanpa path. `no-referrer` tidak dipakai karena YouTube menolak embed tanpa referrer (error 153). |
| Firefox ikut dibersihkan | Profil Firefox dapat `user.js` sendiri: telemetri mati, tracking protection nyala, tidak menyimpan password. |

Yang **tidak** dilakukan: tidak ada IP berbeda-beda per window, tidak ada rotasi proxy,
tidak ada pemalsuan user-agent atau device fingerprint. Semua window keluar lewat jalur
yang sama, jadi view yang tercatat di platform tetap view asli dari satu orang.

---

## Auto-advance

| Platform | Pindah otomatis |
|---|---|
| YouTube | Pakai IFrame Player API — lanjut saat video **benar-benar selesai** (durasi asli). |
| TikTok / Facebook / Instagram | Pakai **timer per stream** (default 60 detik). Embed platform ini tidak menyediakan event "selesai", jadi timer adalah satu-satunya cara. |

---

## Struktur

```
run.py                # runner: cek deps -> migrate -> start server -> buka GUI
build_exe.py          # bikin dist/PlaylistStudio.exe (portable, tanpa Python)
guide.txt             # contekan perintah Windows vs Lubuntu + solusi masalah umum
backend/
  paths.py            # lokasi data/aset, konsisten saat source maupun exe
  db.py               # SQLite + sistem migrasi berversi + semua CRUD
  main.py             # REST API (playlist, item, stream, hit) + serve halaman
  launcher.py         # cari browser, enumerasi monitor, buka/tutup window per stream
  scheduler.py        # jadwal nyala/mati + pemulihan window yang mati sendiri
  probe.py            # cek video masih hidup + ambil judul asli (oEmbed)
  sheets.py           # template Excel + parser impor .xlsx/.csv
  parsers.py          # deteksi platform + embed url + url asli untuk di-hit
static/
  index.html/app.js   # GUI control panel
  player.html/player.js  # halaman player yang jalan di tiap window stream
data/                 # dibuat otomatis: playlist.db + profiles/ (tidak di-commit)
```

### Skema database

| Tabel | Isi |
|---|---|
| `videos` | library global, satu baris per video unik (+ `play_count`) |
| `playlists` | daftar playlist |
| `playlist_items` | isi tiap playlist (hapus di sini ≠ hapus video) |
| `streams` | satu baris per window/kelompok: playlist, monitor, mode, timer, batas sesi, kabar terakhir |
| `schedules` | jadwal nyala/mati per stream atau untuk semua stream |
| `play_log` | satu baris tiap kali sebuah video dicoba diputar; kolom `confirmed` menandai yang benar-benar jalan |
| `schema_migrations` | versi skema, dipakai runner untuk migrate/skip |

Menambah kolom nanti: tambahkan entri versi baru di `MIGRATIONS` (`backend/db.py`),
jangan mengubah versi lama — database yang sudah jalan otomatis ikut naik.

---

## Catatan teknis

- **Autoplay:** browser memblokir autoplay bersuara sebelum ada interaksi. Window stream
  dibuka dengan `--autoplay-policy=no-user-gesture-required` sehingga umumnya langsung
  jalan; kalau tidak, ada tombol **▶ Mulai nonton** di tengah layar (sekali klik per window).
- **Firefox:** didukung penuh — profil terisolasi lewat `-profile`, prefs privasi ditulis
  ke `user.js`, dan karena Firefox tidak punya flag posisi window, window-nya digeser ke
  monitor yang dipilih lewat WinAPI setelah muncul (butuh 1-2 detik). Kalau kamu punya
  Chrome sekaligus Firefox, Chrome dipakai duluan; paksa Firefox lewat `BROWSER_PATH`.
- **Kalau tidak ada satu pun browser di atas:** stream tetap dibuka di browser default,
  tapi **tanpa** profil terisolasi dan tanpa penempatan monitor otomatis.
- **GUI tidak ikut tertutup** saat stream dijalankan. Tiap stream adalah proses browser
  terpisah, jadi kamu bisa terus menambah/menghapus playlist dan menyalakan stream lain
  sementara yang lain tetap main. Menutup satu window stream juga tidak mengganggu window
  lain — statusnya otomatis balik jadi berhenti di GUI dalam ~5 detik.
- **Ctrl+C** di runner menutup semua window stream yang sedang jalan.
#   r e p o s t  
 