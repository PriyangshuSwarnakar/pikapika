\# Pikapika



\*\*Pikapika\*\* is a desktop utility for linguists and NLP/ASR data teams working with Audacity-based audio annotation workflows. It streamlines the repetitive parts of PCM import setup, label file management, duration analysis, and CSV export — all from a single dark-themed GUI built with Python and tkinter.



\---



\## Features



\### PCM Importer

Generates Audacity macro scripts (`.txt`) for batch-importing raw PCM audio files. Supports configurable encoding (8/16/24/32-bit PCM, 32/64-bit float), byte order, channel count (mono/stereo), sample rate, start offset, and amplification. Stereo files are automatically split into left and right WAV channels before import. Macros are written directly to Audacity's Macros folder.



\### Label Exporter

Splits a single combined Audacity label export into individual per-track `.txt` files, named to match the corresponding PCM files. Supports both multi-segment mode (alternating Silence/tag structure) and single-label mode (one label per track). Optionally renames numeric or unnamed tags using a configurable middle tag from a preset list of noise and augmentation categories.



\### CSV Generator

Converts Audacity label `.txt` files into `.csv` files with the header `Start point,End point,Category`. Auto-detects single-label vs. multi-segment format per file. Output is saved alongside the source `.txt` files.



\### Duration Checker

Reads exported label files and computes segment durations. Writes three output folders: \*\*Duration Individual\*\* (per-file breakdown), \*\*Duration Compiled\*\* (all files in one report), and \*\*Duration Middle\*\* (sum of non-boundary segments, for multi-segment mode). Single-label mode skips the middle duration folder.



\---



\## Requirements



\- Python 3.10 or higher

\- No external dependencies — uses only the Python standard library (`tkinter`, `os`, `re`, `struct`, `sys`)



\---



\## Installation



\### Option A — Windows Installer (recommended)



Download `Pikapika\_Setup\_v1.2.exe` from the \[Releases](../../releases) page and run it. No Python installation required.



\### Option B — Run from source



```bash

git clone https://github.com/PriyangshuSwarnakar/pikapika.git

cd pikapika

python pikapika.py

```



Requires Python 3.10+ with tkinter available (included by default in standard Python distributions on Windows).



\---



\## Building from Source (Windows)



Install dependencies:



```bash

pip install pyinstaller

```



Then follow the steps in `BUILD\_INSTRUCTIONS.txt` to produce the `.exe` using PyInstaller and the included `pikapika.iss` Inno Setup script.



\---



\## Usage



Launch the app and use the four tabs:



1\. \*\*PCM Importer\*\* — Add your `.pcm` files, configure import settings, and generate the Audacity macro. The macro is saved to Audacity's Macros folder automatically.

2\. \*\*Label Exporter\*\* — Point to your combined label `.txt` export and your PCM files folder. Select a middle tag if needed, then run to split into individual label files.

3\. \*\*CSV Generator\*\* — Point to a folder of label `.txt` files and run to generate matching `.csv` files.

4\. \*\*Duration Checker\*\* — Point to your exported labels folder and an output base folder, then run to generate duration reports.



\---



\## License



All rights reserved. © Priyangshu Swarnakar

