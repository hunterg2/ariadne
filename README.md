# Ariadne

Ariadne is a local web app for organizing large folders of images. It runs a
small Flask server on your own machine, opens a browser tab, and gives you one
place to sort, rate, tag, search, de-duplicate and edit images without ever
moving the originals unless you ask it to. Folders you add can keep themselves
in step with the disk.

It is fully local and fully private: the browser talks only to the server on
your machine, and nothing is sent anywhere unless you choose a hosted vision
model for tag suggestions (Ollama keeps even those local).

If your images came out of an image generator such as ComfyUI, A1111 or Forge,
Ariadne also reads the prompt and settings out of each file and makes them
searchable. It grew up sorting that kind of output, and the tools suit it.

## What it does

**Library**
- Any folder of images, scanned into an index in the background so a folder
  of fifty thousand files opens as fast as one of fifty. A folder can include
  its subfolders in one grid, and watched folders mirror a directory's
  subfolders into a sidebar group that stays in step with the disk.
- Star ratings (1 to 5), a reject flag and colour labels, with a cull mode
  that steps through a folder as you rate.
- Flat tags with groups and colours, rename and merge; manual collections and
  smart collections (saved searches).
- Details by origin: generated images show prompt, negative, model, LoRAs,
  sampler, steps, CFG and seed (ComfyUI, A1111/Forge and EXIF-based files,
  including prompt lists); camera photos show make, model, lens, exposure and
  place; everything else shows the file facts.
- A query language over the whole library or one folder:
  `prompt: "red dress" & night; tag: portrait; steps: 20...30`. The search
  box suggests fields, your tags, model and sampler names and recent
  searches as you type, and the "i" button shows the full syntax.
- Duplicate finder on a perceptual hash with six strictness levels and a
  review screen that suggests which copy to keep; compare two to six images
  side by side, with a wipe or a difference view.
- Tag suggestions from the prompt, or from a vision model through Ollama, an
  OpenAI-compatible endpoint or the Anthropic API, reviewed before anything
  is written.
- An image editor: marker, highlighter, arrows, shapes, text, blur brush and
  blur area (gaussian, pixelate or unfocus), stamps, crop with ratios, rotate
  and flip, undo. Saves a copy as PNG, JPEG or WebP, never the original, and
  lets you choose whether the copy keeps the generation data, keeps
  everything except location data, or carries no metadata at all.
- Soft delete into a `trash/` subfolder with restore, or the recycle bin.
  Copy, move or zip a selection.

**Everywhere**
- Keyboard first: every frequent action has a key, all rebindable, and
  `Ctrl+K` opens a command palette.
- A phone layout: start it for the network, set a PIN, and the same app
  works by touch on a phone.
- Dark and light themes. Several libraries ("projects") side by side.
- Library export and import as JSON; a database backup on every start.

## Requirements

- Python 3.10 or newer (developed on 3.14, tested in CI on 3.12).
- Flask and Pillow. `requirements.txt` lists them and the launchers install
  them on first run.
- Optional: `send2trash` (hard deletes go to the recycle bin) and `pystray`
  (tray mode).
- A current browser. The frontend is built and committed, so Node is only
  needed to change it.
- Developed on Windows. The launchers also cover macOS and Linux, which are
  less exercised.

## Installation and first run

**Windows, nothing installed:** download `Ariadne-<version>-win64.zip` from
the Releases page, unzip it anywhere and double-click `Ariadne.bat`
(`Ariadne (tray).bat` for the background mode). It carries its own Python
and packages. Your data goes into the `data` folder beside the launchers;
to upgrade, replace the `app` and `python` folders and keep `data`. The zip
is built by `scripts/build_release.py`, which the release workflow runs for
every `v*` tag.

**From the source:**

1. Clone or download this repository into a folder you intend to keep. All of
   the app's data is written next to `app.py`.
2. Start it:
   - Windows: double-click `start.bat`.
   - macOS: double-click `start.command`.
   - Linux: run `./start.sh`.
   - Anywhere: `python -m pip install -r requirements.txt`, then
     `python app.py`.
3. A browser tab opens at `http://127.0.0.1:5000`. If port 5000 is taken the
   server picks the next free one and prints it.
4. Optional: `python make_shortcut.py` puts a desktop shortcut on the
   launcher.

Launcher options, all accepted by the start scripts too:

| Option | Effect |
|---|---|
| `--port N` | Listen on another port. |
| `--host ADDR`, `--lan` | Listen on another address; `--lan` means every interface, so a phone or laptop on the same network can open the address printed at start. Other devices are asked for the PIN set under Settings, Other devices; until one is set they are turned away. |
| `--no-browser` | Do not open a tab. |
| `--tray` | Keep running from a tray icon with no console window (needs `pystray`). Settings can also make this start at logon. |
| `--reload` | Restart when a source file changes (development). |
| `--app-dir DIR` | Keep the database, settings, caches and key file in `DIR` instead of beside `app.py`: a second library, a portable copy, or a scratch one. |

To stop the server, press Ctrl+C in its window, close the window, or choose
Quit on the tray icon.

## Using it

**Add a folder.** In the Library sidebar, add a folder with the folder-plus
button. It is indexed in the background and remembered between runs, and
thumbnails are built as it is read so the grid never waits. A folder's menu
has "Include subfolders" to show everything under it in one grid (`trash`
and dot-folders are skipped; tiles say which subfolder they came from). To
follow a directory whose subfolders come and go, add it under Settings,
Watched folders: each subfolder becomes an entry in a sidebar group that
stays in step with the disk.

**On a phone.** Start with `--lan`, set a PIN, and open the address on the
phone: the sections sit along the bottom, the folder list is behind the
Folders button, the info panel is a sheet, and a swipe moves through the
viewer. Rating with the star row on each tile works by touch.

**Rate, tag, collect.** Click a tile or move with the arrow keys, then press
`1` to `5` for stars, `0` to clear, `X` to reject, `T` to tag. `F` opens
cull mode, which advances after every rating. Select with `S` or Ctrl-click
and the selection bar offers rating, tagging, collections, compare, tag
suggestions, copy, move, zip and trash. The info panel (`Space`) shows
everything known about the focused image.

**Search.** The search box takes free text or the query language. Fields:
`prompt`, `negative`, `title`, `model`, `folder`, `sampler`, `scheduler`,
`camera`, `lens`, `software`, `label`, `kind`, `lora`, `tag`, `collection`
and the numeric `steps`, `cfg`, `width`, `height`, `seed`, `stars`, `iso`.
Separate fields with `;`, join terms with `&` and `||`, quote phrases, use
`...` as a wildcard at either end, and `20...30` for a range. `#portrait` is
shorthand for `tag: portrait`. Save a search as a smart collection.

**Edit.** Right-click a tile (or use the info panel) for Edit. The editor
writes a copy beside the original (`name_edit.png`) or into a folder you
choose, and tags it `edited` so it is easy to find. Its Metadata setting
decides what the copy carries: the generation data only (default),
everything the original had except location data, or nothing.

**Keys.** Settings, Keyboard lists every shortcut and lets you rebind it.
`Ctrl+K` opens the command palette: type to jump to a screen, tool, folder
or collection.

## Where its data lives

Everything is next to `app.py` and all of it is ignored by git:

| Path | What it holds |
|---|---|
| `organizer.db` (+ `-wal`, `-shm`) | The library: the image index, ratings, tags, collections, trash records and cached metadata. The one thing that cannot be rebuilt from your image folders. |
| `ariadne.key` | A random secret that signs the cookie other devices get after entering the PIN. Deleting it only signs them out. |
| `backups/` | A copy of the database taken on every start and before every migration; the last seven are kept. |
| `cache/thumbs/` | WebP thumbnails. Safe to delete at any time. |
| `settings.json` | Preferences, hotkeys, watched folders, tagger and editor defaults. |
| `history.json` | The sidebar: saved folders, groups, pins and order. |
| `projects.json` and `projects/<id>/` | The list of libraries and the data for every library other than the default one. |

To back up, copy `organizer.db` while the app is stopped, or use Tools,
Export ratings and tags for a portable JSON of the parts that cannot be
recomputed. To reset, stop the app and delete the database files and
`cache/`; delete the JSON files and the key as well for a completely fresh
start. Your image folders are untouched by any of this.

If you move an image folder, use "Fix path" on the sidebar entry and point it
at the new location: every rating, tag and collection record follows.

Libraries from the previous build are migrated on first start: liked and
loved become 3 and 5 stars, and the old JSON files are kept as `*.v1.bak`.

## Privacy and safety

- The server binds to `127.0.0.1` unless you pass `--host`. On this
  computer there is no login. Other devices are asked for a PIN (Settings,
  Other devices), which is kept as a salted hash in the database; with no
  PIN set they are turned away. Ten wrong guesses lock a device out for
  fifteen minutes. It is a PIN over plain HTTP, meant for a home network,
  not the open internet.
- Nothing is uploaded anywhere unless you choose a hosted vision model for
  tag suggestions; the local prompt-based tagger and Ollama keep everything
  on your machine.
- API keys for taggers live in `settings.json` in plain text.
- Edits always produce copies. Location data is stripped from every copy
  unless you choose "keep everything" and the original carried it, and even
  then only the camera tags come along, never the GPS directory.

## Development

```
py -3 app.py --no-browser --reload       # backend, serving the built frontend
cd web && npm install && npm run dev     # frontend dev server, proxies /api
cd web && npm run check && npm run build # type-check, then write web/dist
py -3 -m pytest -q                       # backend tests
cd web && npm run e2e                    # browser tests (Playwright, see below)
py -3 scripts/bench_index.py 200000      # time the index on a synthetic library
py -3 scripts/make_sample_library.py DIR # a folder of sample PNGs with prompts
```

The browser tests start their own Ariadne with `--app-dir` on a throwaway
directory under the system temp folder, generate a sample library there and
drive the built frontend in Chromium, so run `npm run build` first and
`npx playwright install chromium` once. They never touch your real library.
CI runs them on every push alongside the backend tests and the frontend
check.

- `ariadne/` is the application: `api/` blueprints, `services/` behaviour,
  `migrations/` versioned schema changes, `metadata.py` the extractor and
  the EXIF reader, `tagger.py` the tag backends. `app.py` only starts it.
- `web/src` is the Svelte 5 frontend: `routes/` one file per screen,
  `lib/library` the Library parts and full-screen tools, `lib/editor` the
  image editor's document, `lib/api.ts` the typed client. `web/dist` is the
  built bundle and is committed, so the launchers never need Node.
- GitHub Actions runs the tests on Windows and the frontend build and the
  browser tests on Ubuntu.

## Helper scripts

- `make_shortcut.py` draws `icon.png` and `icon.ico` and creates a desktop
  shortcut to the launcher.
- `diagnose_metadata.py FOLDER [N]` reports what the first N PNGs in a folder
  actually carry and what the parser reads out of them. Use it when the
  prompt panel shows the wrong text or nothing at all.
- `python metadata.py IMAGE ...` prints the extracted settings for each file.

## Troubleshooting

**"Python was not found" or the install step fails.** Install Python 3.10 or
newer from python.org and tick "Add Python to PATH", then run the launcher
again. If pip cannot reach the internet, install the packages by hand:
`python -m pip install -r requirements.txt`.

**The browser tab does not open, or shows "connection refused".** The
launcher window prints the address it is actually serving, which may not be
port 5000 if that was busy. If the window closed immediately, run
`python app.py` from a terminal to see the error.

**"The frontend has not been built."** `web/dist` is missing. Run
`npm install` and `npm run build` in `web/`, or pull a build that includes it.

**Thumbnails or details look stale.** They are cached by file size and
modification time, so a file edited in place is picked up, but a bad read is
remembered. Settings, Library has "Rebuild thumbnails" and "Re-read
metadata"; a folder's menu has "Rescan".

**A folder shows as broken.** The drive letter or path changed. Use "Fix
path" on the entry rather than adding it again, so the records follow.

## Status

A personal tool, built for one user and published as a code sample rather
than a supported product. Keep your own backups of anything you care about.

## Licence

Copyright (c) 2026 hunnaG. Released under the GNU General Public License v3.0; see [LICENSE](LICENSE).
