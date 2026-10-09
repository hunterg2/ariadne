# Ariadne

Ariadne is a local web app for organizing large folders of images. It runs a
small Flask server on your own machine, opens a browser tab, and lets you rate,
tag, search, de-duplicate, edit and export images without ever moving the
originals unless you ask it to. Folders you add can keep themselves in step
with the disk.

It is fully local and fully private: the browser talks only to the server on
your machine, and nothing is sent anywhere unless you choose a hosted vision
model for tag suggestions (Ollama keeps even those local).

If your images came out of an image generator such as ComfyUI, A1111 or Forge,
Ariadne also reads the prompt and settings out of each file and makes them
searchable. It grew up sorting that kind of output, and the tools suit it.

The page calls itself "Image Organizer"; Ariadne is the project name.

## Features

- Browse any folder as a thumbnail grid that fills in progressively, with
  cached WebP thumbnails so reopening a folder is near instant.
- Rate images as liked or loved with one key, and tag them with free text.
  Ratings and tags live in a database, not in the files or folder layout.
- Read generation metadata (prompt, negative prompt, model, LoRAs, steps, CFG,
  sampler, scheduler, seed) from ComfyUI, A1111/Forge and EXIF-based files,
  including workflows that used a prompt list.
- Search one folder or the whole library with a small query language
  (`prompt: "red dress" & night; tag: portrait; steps: 20...30`).
- Sidebar of saved folders with groups, pins, aliases and drag ordering, plus
  auto-updating groups that mirror the subfolders of any folder you set (a
  camera import, a downloads folder, a generator's output directory).
- Duplicate finder using a perceptual hash, with a review screen that suggests
  which copy to keep, and a side-by-side compare view.
- Soft delete into a `trash/` subfolder beside the image, with restore and
  purge; or hard delete to the recycle bin.
- Copy, move or zip a selection to another folder.
- An image editor for cropping, rotating, blurring or pixelating regions,
  stamping and adding text. Saves a copy, never the original, and lets you
  choose whether the copy keeps the generation data, keeps everything except
  location data, or carries no metadata at all.
- Automatic tag suggestions from the prompt, or from a vision model through
  Ollama, an OpenAI-compatible endpoint or the Anthropic API. Suggestions are
  reviewed before anything is written.
- Multiple libraries ("projects"), library export and import as JSON, and an
  automatic database backup on every start.

## Requirements

- Python 3.10 or newer (tested on 3.10 and 3.14).
- Flask 3 and Pillow 10 or newer. `requirements.txt` lists them, and the
  launchers install them on first run.
- Optional: `send2trash`, which makes hard deletes go to the recycle bin
  instead of removing the file outright.
- A modern browser. Chromium-based browsers and Firefox both work.
- Developed on Windows. The launchers and the shortcut maker also cover macOS
  and Linux, but those are less exercised.

## Installation and first run

1. Clone or download this repository into a folder you intend to keep. All of
   the app's data is written next to `app.py`, so pick somewhere permanent.
2. Start it:
   - Windows: double-click `start.bat`. It finds Python, installs Flask and
     Pillow if they are missing, and runs the server.
   - macOS: double-click `start.command`.
   - Linux: run `./start.sh`.
   - Anywhere: `python -m pip install -r requirements.txt`, then
     `python app.py`.
3. A browser tab opens at `http://127.0.0.1:5000`. If port 5000 is taken by
   something else the server picks the next free one and prints it. Use
   `--port 8080` to choose, and `--no-browser` to stop it opening a tab.
4. Optional: `python make_shortcut.py` draws the icon and puts a desktop
   shortcut that points at the launcher. `--dev` makes a shortcut that restarts
   the server whenever a file changes, `--name "Something"` renames it.

To stop the server, press Ctrl+C in its window or close the window.

## Using it

1. **Add a folder.** In the sidebar choose to add a folder and pick one in the
   browser dialog (it lists your drives and lets you walk down). The folder is
   remembered between runs. Nothing is written into it.
2. **Rate and tag.** Hover or click a tile and press a key:

   | Key | Action |
   |---|---|
   | `1` | Mark liked |
   | `2` | Mark loved |
   | `Space` | Show the prompt and generation settings |
   | `T` | Tag the image (or the selection) |
   | `Backspace` / `Delete` | Trash |
   | `C` | Reveal in the file manager |
   | `S` | Add to the selection |
   | `F` | Cull mode: step through a folder, rating as you go |
   | `Left` / `A`, `Right` / `D` | Previous / next image |

   The keys are rebindable in Settings, and "Keyboard shortcuts" in the app
   lists the current set.
3. **Filter and search.** The filter row narrows the open folder by rating, tag
   or text. "Everywhere" runs the same query against every image the app has
   ever indexed. Fields are `prompt`, `negative`, `title`, `model`, `folder`,
   `sampler`, `scheduler`, `lora`, `tag`, and the numeric `steps`, `cfg`,
   `width`, `height`, `seed`. Separate fields with `;`, join terms with `&`
   and `||`, quote phrases, use `...` as a wildcard at either end, and
   `20...30` for a numeric range. `#portrait` is shorthand for `tag: portrait`.
4. **Open an image.** Click a tile to open the viewer, with zoom, a filmstrip,
   the prompt panel (which also names where each value was read from), and the
   same keys as the grid. From there you can open the editor.
5. **Clean up.** Select tiles (click with `S` or use the selection bar) and
   trash, copy, move or zip them from the selection bar or the right-click
   menu. The duplicate finder is on the toolbar; its review screen marks the
   copies to drop and trashes them in one go.
6. **Watch a folder.** In the "Add a folder" dialog, under "Auto-updating
   folders", add one. Each of its subfolders appears as an entry inside a group
   in the sidebar, and the group is rebuilt from disk on every refresh.
   Subfolders you drag out of the group stay out.

Where files end up:

- Rating and tagging never move a file. Both are rows in the database keyed on
  the file's full path.
- Trash, in the default soft mode, moves the file into a `trash/` subfolder
  next to it and records where it came from so it can be restored. Hard mode
  sends it to the recycle bin when `send2trash` is installed and removes it
  outright otherwise.
- Copy, move and zip go to the folder you pick. A move carries the ratings and
  tags across.
- The editor writes a copy: `name_edit.png` beside the original, or a file in
  a folder you choose. The original is never modified. Its Metadata setting
  decides what the copy carries: the generation data only (default),
  everything the original had except location data, or nothing. Edited copies
  are tagged `edited` so they can be found later (this can be turned off in
  Settings).

## Where its data lives

Everything is next to `app.py` and all of it is ignored by git:

| Path | What it holds |
|---|---|
| `organizer.db` (+ `-wal`, `-shm`) | The library: ratings, tags, trash records, cached metadata and thumbnail bookkeeping. The one thing that cannot be rebuilt from your image folders. |
| `backups/` | A copy of the database taken on every start; the last seven are kept. |
| `cache/thumbs/` | WebP thumbnails. Safe to delete at any time; they are rebuilt on demand. |
| `settings.json` | Hotkeys, watched folders, look and feel, tagger and editor defaults. |
| `history.json` | The sidebar: saved folders, groups, pins and order. |
| `projects.json` and `projects/<id>/` | The list of libraries and the data for every library other than the default one. |
| `categories.json`, `tags.json` | Only read by the one-time migration from the original JSON layout, then renamed to `*.v1.bak`. A fresh install never needs them. |
| `metadata_report.txt` | Written by `diagnose_metadata.py` in the current directory. |

To back up: the automatic copies in `backups/` cover the last seven starts.
For anything longer-lived, stop the app and copy `organizer.db`, or use
"Export ratings & tags" under Settings, which writes a JSON file that the
import option beside it can merge back later.

To reset: stop the app and delete `organizer.db`, `organizer.db-wal`,
`organizer.db-shm` and `cache/`. Delete `settings.json`, `history.json` and
`projects.json` as well for a completely fresh start. Your image folders are
untouched by any of this.

If you move an image folder, use "Fix folder" on the broken sidebar entry
and point it at the new location: every rating, tag and trash record is carried
across.

## Routes

`templates/index.html` is served at `/` and talks to these endpoints. All
return JSON unless noted. Every path the page passes is checked against the
folders you have added before the server will read or move it.

Images and thumbnails
- `GET /thumb?path=` cached WebP thumbnail (falls back to the original)
- `GET /image?path=` the original file
- `GET /api/images/check`, `GET /api/images/stream` (server-sent events, one
  batch of tiles per event; `folder=__search__&q=` searches the whole library)
- `GET /api/prompt?path=` the raw workflow or parameters chunk
- `POST /api/reveal` open the file manager at the file

Sidebar and folders
- `GET|POST /api/history`, `POST /api/history/sync`, `POST /api/history/update`
- `GET /api/history/check` which saved folders still exist, with counts
- `POST /api/history/repath` move a folder's records to a new path
- `GET /api/browse?path=` directory listing for the folder picker

Ratings, tags and actions
- `POST /api/action` rate (`liked`, `loved`, `rest`) or `trash` a list of paths
- `POST /api/tags` set, add or remove tags; `GET /api/tags/all` tag counts
- `POST /api/tag/check`, `GET /api/tag/auto` (server-sent events) tag suggestions
- `GET /api/trash`, `POST /api/trash/restore`, `POST /api/trash/purge`

Export and editing
- `POST /api/export` copy or move; `POST /api/export/zip` zip download
- `POST /api/edit/save` write the editor's canvas as a new file, with the
  metadata mode chosen on screen

Library, projects and maintenance
- `GET|POST /api/settings`
- `GET /api/projects`, `POST /api/projects/create|switch|rename|delete`
- `GET /api/library/export` (JSON download), `GET /api/library/stats`,
  `POST /api/library/import`
- `GET /api/cache/stats`, `POST /api/cache/clear`, `POST /api/cache/prune`
- `GET /api/stats`

## Helper scripts

- `make_shortcut.py` draws `icon.png` and `icon.ico` and creates a desktop
  shortcut to the launcher. Run it again only if you move the folder.
- `diagnose_metadata.py FOLDER [N]` reports what the first N PNGs in a folder
  actually carry: which text chunks, whether they are identical across files,
  which nodes the workflow contains, and what the app's parser reads out of
  them. Use it when the prompt panel shows the wrong text or nothing at all.
- `python metadata.py IMAGE ...` prints the extracted settings for each file.

## Troubleshooting

**"Python was not found" or the install step fails.** Install Python 3.10 or
newer from python.org and tick "Add Python to PATH" in the installer, then run
the launcher again. If pip cannot reach the internet, install the two packages
by hand: `python -m pip install -r requirements.txt`.

**The browser tab does not open, or shows "connection refused".** Look at the
launcher window: it prints the address it is actually serving, which may not
be port 5000 if that was busy. Open that address by hand. If the window closed
immediately, run `python app.py` from a terminal to see the error.

**Thumbnails or prompts look stale or wrong.** Thumbnails and metadata are
cached by file size and modification time, so an edited file in place is
picked up automatically, but a bad read is remembered. Settings, Maintenance
has "Rebuild thumbnails", "Re-read metadata" and "Clean up thumbnails".
Deleting `cache/` while the app is stopped does the same as the first.

**A folder shows as broken.** The drive letter or path changed. Use "Fix
folder" on the entry to point it at the new location rather than adding it
again, so the ratings and tags follow.

## Status

This is a personal tool in alpha. It has one user, no tests, and features that
were added as they were needed. It is published as a code sample, not as a
supported product; expect rough edges, and keep your own backups of anything
you care about.

## Licence

Copyright (c) 2026 hunnaG. Released under the GNU General Public License v3.0; see [LICENSE](LICENSE).
