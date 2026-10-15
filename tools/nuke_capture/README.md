# NukeX reference capture

Windows-only development harness. Launches an installed, licensed NukeX on a
separate Windows desktop. It never switches to that desktop or injects desktop
mouse or keyboard input. The existing NukeX session is not attached or modified.

This uses the real GUI with an isolated desktop, not Nuke's terminal mode.
Qt captures happen inside Nuke on its GUI thread. No runtime Python packages
are required beyond Python on the host and Nuke's bundled PySide6.

From the repository root:

```powershell
python tools/nuke_capture/capture.py --node Constant --widget Properties.1
python tools/nuke_capture/capture.py --fixture --widget Viewer.1
python tools/nuke_capture/capture.py --fixture --widget DAG.1
python tools/nuke_capture/capture.py --atlas --timeout 240
```

Use `--exe` for another Nuke installation and `--output` for a new output
directory. Existing output directories are rejected. `--timeout` defaults to
120 seconds. A separate GUI license may be needed under some license setups.

Each run uses a disposable in-memory scene and temporary directory. The
launcher terminates only the process it created and closes its desktop handle.
Nuke's `--safe` mode excludes user startup scripts and OFX plug-ins. The capture
script is passed explicitly on the command line. It does not install a global
startup script or change global environment variables.

## Explore and target

Run without `--node` to inspect the empty workspace. `widgets.json` contains
visible widget classes, object names, and logical coordinates relative to the
main window. `menus.json` contains menu paths. Names are version-dependent;
inspect the inventory rather than guessing them.

`--node Constant` creates a Constant in the disposable scene, opens its
properties, and exports knob names, classes, and labels to `knobs.json`.

`--widget Properties.1` selects exactly one visible named widget. Missing or
ambiguous selectors fail. `--rect X Y WIDTH HEIGHT` crops in logical coordinates
relative to the selected widget, or the main window when no widget is supplied.
Out-of-bounds crops fail. The image uses the display's physical pixel scale.

Outputs:

- `main.png`: complete main window.
- `selected.png`: requested widget or rectangle.
- `widgets.json`, `menus.json`, and optional `knobs.json`: inspection data.
- `request.json`, `started.json`, and `result.json`: request and result evidence.
- `dialogs.json`: blocking dialogs, when present. No dialog is auto-accepted.

## GPU capture and UI atlas

`--fixture` creates CheckerBoard2 -> Grade -> Viewer. The harness waits for
nonblank viewer and graph surfaces before saving. `--size WIDTH HEIGHT` sets
the main window size in logical pixels; the default is 1600 x 1000.

Nuke uses native `Foundry::UI::GLWindow` surfaces inside its Qt widgets.
The harness reads each presented OpenGL front buffer through a temporary WGL
context, restores the previous context, and composites pixels into the Qt image.
Native client dimensions determine readback size. Widget coordinates determine
placement. This avoids blank GPU regions in ordinary Qt snapshots.
`gpu.json` records surface ownership, dimensions, normalized hashes, and color counts.

`--atlas` implies `--fixture`. It explores default tabs, top-level menus,
14 representative node panels, and six workspace layouts. It sends local Qt
events inside the isolated process; it never moves the desktop cursor.
The atlas changes Grade brightness and position to verify live pixels.
Failed checks or capture cases produce a nonzero launcher exit.

Additional outputs:

- `index.html`: searchable screenshot gallery.
- `atlas-manifest.json`: captured states and failures.
- `atlas/*.png` and matching JSON: images and visible control metadata.
- `atlas/knobs-*.json`: knob labels, types, tooltips, and serialized values.
- `menu-inventory.json`, `qt-menu-inventory.json`, `tab-inventory.json`: UI structure.
- `verification.json`: before/after GPU hashes and change checks.
- `progress.json`: current case while the atlas runs.

Verified on installed NukeX 17.1v2: 41 images, no failed cases, both live GPU
checks passed, all images visually reviewed. See [UI-MAP.md](UI-MAP.md) for coverage.

`ok: true` means the requested checks passed. It does not prove complete UI
coverage or pixel parity on another driver. Settling uses bounded delays;
arbitrary asynchronous operations are not guaranteed to finish. Other versions,
display scales, floating windows, and external plug-ins remain unverified.

## Enumerate and capture node types

```powershell
python tools/nuke_capture/catalog.py --output .captures/nuke-nodes
```

This resumes an existing catalog or creates a new one. Each isolated session
processes up to 60 candidates. `--batch-size` and `--timeout` control session
size and maximum duration. Each node gets property and graph PNGs, serialized
knobs, visible controls, its actual class, and source evidence.

Enumeration combines the loaded registry, shipped DLL and gizmo filenames,
literal constructors in the shipped toolbar script, bundled OFX descriptors,
and registry additions discovered while loading nodes. Library files that do not create nodes remain
listed with their errors. Candidate count is not node count. External OFX
plugins are outside this inventory. Forcing the full registry loads external
OFX plugins even in safe mode, so the catalog does not use that operation.

Nodes are unconnected and captured at their initial visible property state.
The harness does not run rendering, tracking, training, or file workflows.
It deletes each temporary node after capture. Session failures leave an explicit
interrupted record; subsequent batches continue with the remaining candidates.
Dialogs are captured without accepting them, then the session ends. A node only
counts as captured when its named property panel appears. Structural objects
without a panel have `no_panel` records. Existing records are retained on resume.

Open `index.html` for the gallery or `nodes.csv` for the enumerated list.
`coverage.json` distinguishes captured types, actual classes, unavailable
candidates, non-node libraries, errors, and interrupted attempts.
Rebuild these outputs without launching Nuke using `--build-only`.

The verified 17.1v2 sweep processed 776 candidates. It captured 604 entries
covering 602 distinct classes, with 1,209 validated PNGs. The remaining records
are 138 non-node libraries, 15 unavailable constructors, nine interrupted
constructors, eight creation errors, and two objects without node panels.
All 13 bundled OFX descriptors are listed, but their nodes cannot load in safe
mode. Full counts and individual reasons remain in the generated catalog.
Captures cover the initial property tab and visible region, not every tab or setting.

The optional `review_catalog.py OUTPUT` script checks image hashes and dimensions
and builds contact sheets. It requires Pillow on the host; capture does not.
Run bookkeeping tests with:

```powershell
python -m unittest discover -s tools/nuke_capture -p test_catalog.py
```

## Sequential UI exploration

```powershell
python tools/nuke_capture/explore.py --output .captures/nuke-expanded --catalog .captures/nuke-nodes
```

Runs layouts, nested menus, graph states, viewer states, populated panels,
dialogs, and node properties in order. Only one Nuke capture process runs at a
time. `--catalog` uses one previously captured type per actual node class,
in batches of 40. Without it, properties use a representative list.

`--sections layouts menus graph viewer panels dialogs properties interactions`
selects the sequence. `interactions` adds pane menus, divider sizes, and playback.
Existing run directories are retained; `--build-only` rebuilds the linked gallery
and coverage report. A run name such as `menus-retry` records a separate retry.
An interrupted batch is retained as evidence; use `capture.py --explore properties
--types PATH.json --output NEW_DIRECTORY` to retry a JSON array of missing types.

Layouts are discovered from Workspace. NukeX 17.1v2 exposes Compositing, Large
Node Graph, Large Viewer, Scripting, Animation, Floating, 3D, and Viewer Monitor
Out. Floating panes receive separate images. Empty internal chart windows do
not count as captured UI. Alternate window sizes are captured separately.

Properties include visible tabs, dropdown menus, expanded sections, and scroll
pages. Shared Node-tab controls are explored once per session; each node still
gets its own Node-tab image. Common nodes also exercise color, animation, link,
and selected conditional controls. This does not enumerate every value or every
combination of controls. Some controls appear only after loading suitable media.

Only allowlisted dialog commands run. File, render, and settings dialogs are
captured and canceled. Menu discovery never executes leaf commands. No render,
tracking, training, save, or export is submitted. Existing unavailable OFX and
internal node failures remain documented in the original node catalog.

Each capture includes control metadata, image dimensions, and a PNG hash.
New sessions freeze the Python capture sources in their output directory and
record source hashes. Local Qt events stay inside the isolated Nuke process.
`capture.py --scale FACTOR` changes Qt scaling for that process only; inspect the
reported device pixel ratio rather than assuming the multiplier is the final scale.

```powershell
python tools/nuke_capture/review_explore.py .captures/nuke-expanded
python -m unittest discover -s tools/nuke_capture -p test_explore.py
```

Image validation checks hashes, dimensions, and decoding. Contact sheets support
visual inspection; their creation does not establish visual correctness. See
`coverage.json` for historical failures, recovered cases, and missing property types. A `review-exclusions.json` object maps rejected run
names to reasons. Excluded runs retain evidence but do not contribute images
to the gallery or unresolved-failure totals.

## API references

- https://learn.foundry.com/nuke/developers/16.0/pythondevguide/startup.html
- https://learn.foundry.com/nuke/content/comp_environment/configuring_nuke/command_line_operations.html
- https://github.com/AcademySoftwareFoundation/openfx/blob/main/include/ofxCore.h

AtomicCraft's selected UI and graphics stack is Rust, egui, and wgpu. This Python
harness only gathers references from NukeX; it is not an application dependency.
