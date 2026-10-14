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

`ok: true` means capture and metadata export succeeded. It does not establish
that GPU-rendered regions are correct. Inspect images before using them as
references. Viewer and node graph pixels require separate validation.

The current wait is a bounded settling delay, not a proof that every asynchronous
viewer operation finished. This first harness does not click arbitrary controls
or attach to the existing scene.

## Sources

- https://learn.foundry.com/nuke/developers/16.0/pythondevguide/startup.html
- https://learn.foundry.com/nuke/content/comp_environment/configuring_nuke/command_line_operations.html

AtomicCraft's selected UI and graphics stack is Rust, egui, and wgpu. This Python
harness only gathers references from NukeX; it is not an application dependency.
