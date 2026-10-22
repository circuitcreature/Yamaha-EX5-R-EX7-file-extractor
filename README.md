# Yamaha EX5(R)/EX7 file extractor

Python tools that pull MIDI, audio and name lists out of Yamaha EX5, EX5R, and EX7 save files.
They use only the Python 3 standard library, so there is nothing to install.

> **AI disclosure:** AI tools were used to create this project.

## Usage

Point each tool at a folder of EX5 files (subfolders are searched too). Run from the project root:

```sh
python3 ex5_to_midi.py ~/ex5-disks     # patterns -> Output/<name>/*.mid
python3 ex5_samples.py ~/ex5-disks     # samples  -> Output/Samples/<name>/*.wav
python3 ex5_inventory.py ~/ex5-disks   # summary  -> Output/INVENTORY.txt
```

Each tool also takes individual files or several paths at once, and `-o` to choose the output location.
`ex5_samples.py --rate 22050` forces one sample rate on every sample, if a bank plays back off-pitch.

## EX5 file types

| Extension | Header | Contents | Extracted by |
|---|---|---|---|
| `.S1P` | `SY1200PTN` | A pattern: up to 55 sections × 8 tracks of phrases | `ex5_to_midi.py` |
| `.S1M` | `SY1200SPA` | Sample banks: the raw audio, plus keybank layouts | `ex5_samples.py` |
| `.S1V` | `SY1200VCA` | User voice bank (256 voices) | names only, in the inventory |
| `.S1Y` | `SY1200SYT` | System settings, performances and a voice bank | names only, in the inventory |
| `.S1A` | `SY1200ALL` | Full backup containing SYT, KMAP, SPA and SEQ blocks | all three tools |

The SEQ block inside an `.S1A` holds the pattern that was in memory, and `ex5_to_midi.py` exports it like a `.S1P`.

## What you get

**MIDI** (`ex5_to_midi.py`)
- One type-1 MIDI file per section, plus `<name>_all.mid` with every section in order.
- Each section has 8 tracks on channels 1–8, its own tempo, and phrases looped to the section's length.
- Notes, control changes, pitch bend and SysEx are included.
- Sections with a name (for example `P Funk 1`) carry it in the file name and in a marker.
- Damaged phrase data is salvaged where possible, and a warning is printed.

**WAV** (`ex5_samples.py`)
- One mono 16-bit WAV per sample, with a `smpl` chunk holding the root key and loop points.
- The EX5 stores each sample as 16-bit, packed 12-bit, or 8-bit (sign-magnitude or two's complement). A flag in each sample record says which, and one bank can mix them.
- The files store no sample rate. Pitch analysis gave 44.1 kHz for 16-bit samples and 48 kHz for 12- and 8-bit ones, and those are the defaults.

**Inventory** (`ex5_inventory.py`)
- A text listing of every file: pattern sections, sample names, voice names, performance names.
- Names are found by matching record patterns, not a full parse, so a few may be missing.

## Tools

- `ex5_pattern.py`: pattern parser. Its docstring documents the file and phrase byte formats.
- `ex5_to_midi.py`: pattern to MIDI exporter.
- `ex5_samples.py`: sample-bank to WAV exporter. Its docstring documents the SPA layout.
- `ex5_inventory.py`: file summary.

## Not decoded

The voice and performance parameters (envelopes, filters, effects and so on), the key map, and song-mode sequences.
