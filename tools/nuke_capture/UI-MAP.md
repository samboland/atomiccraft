# NukeX UI reference map

Observed in NukeX 17.1v2 on Windows, 2026-10-14. The reference window measures
1600 x 1000 logical pixels, with 2400 x 1500 output at 150% display scaling.

Reproduce from the repository root:

```powershell
python tools/nuke_capture/capture.py --atlas --timeout 240
```

Open `index.html` in the printed output folder. Each image links to inspection
data. `atlas-manifest.json` records coverage and failures.

## Observed structure

| Area | Visible structure | Implementation use |
| --- | --- | --- |
| Main window | File, Edit, Workspace, Viewer, Render, Cache, Help menus; left node toolbar; docked panes | Build the egui shell and menu placeholders from exported paths |
| Viewer | Channel and view selectors, A/B inputs, display controls, image canvas, image status, timeline, transport | Keep image rendering separate from controls; use wgpu for the image canvas |
| Node Graph | Dark canvas, node thumbnails, labeled nodes, directional connections, overview in larger layouts | Use graph coordinates independent of dock geometry |
| Properties | Scrollable node panels, node header, tabs, channel selectors, numeric fields, toggles and specialized controls | Generate common controls from exported knob classes and labels |
| Curve Editor | Curve list and grid, toolbar | Provide a separate dock pane with animation placeholders |
| Dope Sheet | Track list and timeline | Share animation data with Curve Editor |
| Background Renders | Empty render queue | Provide a queue pane |
| Scene Graph | Search, hierarchy table, selection controls | Reserve the pane before implementing 3D evaluation |
| Script Editor | Editor and output regions in Scripting workspace | Reserve the pane before choosing scripting support |

The default workspace puts Viewer above Node Graph on the left, with Properties
on the right. Background Renders and Scene Graph share the right tab group.
Curve Editor and Dope Sheet share the lower-left tab group.

## Initial atlas coverage

The verified run produced 41 images with no failed cases:

- One initial workspace and four isolated panels.
- Two changed states that verify live viewer and graph pixels.
- Seven default tab states.
- Seven top-level menu popups.
- Fourteen initial node property panels.
- Six workspace states.

Node panels: Read, Write, Constant, CheckerBoard2, Grade, ColorCorrect, Blur,
Merge2, Transform, Shuffle2, Keyer, Roto, Tracker4, CameraTracker.

Workspaces: Large Node Graph, Large Viewer, Scripting, Animation, 3D, Compositing.

The API inventory contains 176 Nuke entries, 564 Nodes entries, 51 Viewer
entries, and 15 Animation entries. These counts include submenus and separators;
they do not count implemented node classes. Pane and Node Graph API inventories
are empty in this session. Native Qt menu actions are exported separately.

## Evidence for automated reuse

`menu-inventory.json` supplies menu paths and available shortcut metadata.
`qt-menu-inventory.json` supplies visible native menu labels and action states.
`tab-inventory.json` supplies pane groupings. Per-image JSON supplies widget
classes, names, rectangles, tooltips, text, selections, and combo choices.
`atlas/knobs-*.json` supplies knob names, labels, types, tooltips, and serialized values.

Use these exports to generate placeholder menus and common property controls.
Use screenshots for spacing, colors, hierarchy, and specialized controls.
Native class names identify reference controls; they are not Rust dependencies.

## Initial atlas verification and limits

Viewer pixels changed after Grade multiply changed from 0.7 to 0.15.
Graph pixels changed after Grade moved from (0, 100) to (180, 100).
Normalized GPU buffer hashes and screenshots record both checks.
All 41 images were visually reviewed through contact sheets.

The initial atlas captures visible initial states, not complete NukeX behavior. Nested menu
popups, context menus, scrolled properties, other property tabs, dialogs, floating
workspaces, monitor output, external plug-ins, and other display scales were not covered by the initial atlas.
The 3D workspace uses the same 2D fixture; no populated 3D scene was tested.
Fixed settling delays remain between atlas actions. Driver portability is untested.
No Rust shell, compositor, or .nk importer is implemented yet.

## Sequential exploration

`explore.py` extends the initial atlas with eight Workspace layouts, their tabs,
floating panes, different window sizes, nested menus, graph states, viewer
controls, dialogs, and populated animation, Roto, tracking, and 3D fixtures.

Workspace discovery includes Floating and Viewer Monitor Out. Do not scope the
application from the default Compositing layout alone. Node properties are
explored per type: visible and nested tabs, menus, section expanders, and scroll
pages. Shared Node-tab controls are explored once per session.

The generated `coverage.json` is the authority for captures, failures, retries,
and missing types. A saved screenshot records an observation; it does not prove
that the requested action changed the UI. Inspect its pixels before using it as
behavioral evidence. `validation.json` checks PNG hashes, dimensions, and decoding.
Empty internal chart windows are excluded from the gallery.

Safe-mode OFX limitations from the node catalog still apply. Arbitrary knob
combinations, imported-media workflows, render jobs, and external plugins are
not established by these captures. No Rust application is implemented yet.

## Implementation references

Sam's decision, 2026-10-14: use ArtCraft apps as implementation references and
reuse suitable code under their Apache-2.0 option. Prefer existing work over
manual reimplementation. Keep NukeX captures as the reference for AtomicCraft's
layout and interaction behavior.

Candidate sources checked on 2026-10-14:

- [EffectCraft](https://github.com/storytold/effectcraft): compositing, effects,
  keyframes, and render controls.
- [FilmCraft](https://github.com/storytold/filmcraft): video and audio handling,
  playback, and timeline behavior.
- [PhotoCraft](https://github.com/storytold/photocraft): image processing and
  image-editing controls.
- [craft-libs](https://github.com/storytold/craft-libs): shared Rust libraries.

These are candidates, not selected dependencies. Before importing code, record
the source repository and commit, check its license and file notices, and retain
required attribution and notices. No ArtCraft source has been imported yet.
