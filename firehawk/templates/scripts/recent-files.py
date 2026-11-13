#!/usr/bin/env python3
"""Two fixed-folder popups. Native URI drag source; never uploads or moves files."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import stat
import sys


FOLDERS = {'downloads': ('Downloads', Path('Downloads')),
           'screenshots': ('Screenshots', Path('Pictures/Screenshots'))}
PARTIAL_SUFFIXES = ('.part', '.crdownload', '.download', '.tmp')


def folder_path(kind, home=None):
    return (home or Path.home()) / FOLDERS[kind][1]


def recent_files(folder, limit=5):
    """Newest modified regular files only; no recursion, hidden files or symlinks."""
    entries = []
    try:
        with os.scandir(folder) as scan:
            for entry in scan:
                if entry.name.startswith('.') or entry.name.lower().endswith(PARTIAL_SUFFIXES):
                    continue
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except OSError:
                    continue  # A download may disappear/rename during the scan.
                if stat.S_ISREG(metadata.st_mode):
                    entries.append((metadata.st_mtime_ns, entry.name, Path(entry.path), metadata))
    except FileNotFoundError:
        return []
    entries.sort(key=lambda item: (-item[0], item[1]))
    return [(path, metadata) for _, _, path, metadata in entries[:limit]]


def file_uri(path):
    return path.absolute().as_uri()


def run_popup(kind):
    # Keep enumeration and tests usable without a GUI/display or PyGObject.
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gdk, Gio, GLib, Gtk, Pango

    class Popup(Gtk.Application):
        def __init__(self):
            super().__init__(application_id='com.firehawk.Files.' + kind.capitalize(),
                             flags=Gio.ApplicationFlags.FLAGS_NONE)
            self.window = None
            self.dragging = False
            self.error_dialog = False

        def do_activate(self):
            if self.window is not None:
                self.window.destroy()  # Clicking the same bar button toggles it closed.
                return
            self.window = Gtk.ApplicationWindow(application=self)
            window = self.window
            window.set_title('Ember Files — ' + FOLDERS[kind][0])
            window.set_wmclass('firehawk-files', 'FirehawkFiles')
            window.set_decorated(False)
            window.set_resizable(False)
            window.set_default_size(460, -1)
            window.set_type_hint(Gdk.WindowTypeHint.DIALOG)
            window.set_skip_taskbar_hint(True)
            window.set_skip_pager_hint(True)
            window.get_style_context().add_class('firehawk-files')
            window.connect('destroy', self.on_destroy)
            window.connect('key-press-event', self.on_key)
            window.connect('focus-out-event', self.on_focus_out)
            # A real panel popup on Wayland, not a tiled application window.
            if 'Wayland' in type(Gdk.Display.get_default()).__name__:
                try:
                    gi.require_version('GtkLayerShell', '0.1')
                    from gi.repository import GtkLayerShell
                    if not GtkLayerShell.is_supported():
                        raise RuntimeError('Compositor does not support layer shell')
                    GtkLayerShell.init_for_window(window)
                    GtkLayerShell.set_namespace(window, 'firehawk-files')
                    GtkLayerShell.set_layer(window, GtkLayerShell.Layer.TOP)
                    GtkLayerShell.set_anchor(window, GtkLayerShell.Edge.TOP, True)
                    GtkLayerShell.set_anchor(window, GtkLayerShell.Edge.LEFT, True)
                    GtkLayerShell.set_margin(window, GtkLayerShell.Edge.TOP, 54)
                    GtkLayerShell.set_margin(window, GtkLayerShell.Edge.LEFT, 14)
                    GtkLayerShell.set_keyboard_mode(window, GtkLayerShell.KeyboardMode.ON_DEMAND)
                    # No exclusive zone: this popup must not rearrange the desktop.
                except (ImportError, ValueError, RuntimeError) as error:
                    print('Ember: layer-shell popup unavailable: ' + str(error), file=sys.stderr)
            css = Gtk.CssProvider()
            css.load_from_path(str(Path(__file__).with_name('recent-files.css')))
            Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css,
                                                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            content.set_border_width(14)
            window.add(content)
            header = Gtk.Box(spacing=12)
            title = Gtk.Label(label=FOLDERS[kind][0].upper() + ' / LAST 5', xalign=0)
            title.get_style_context().add_class('folder-heading')
            header.pack_start(title, True, True, 0)
            close = Gtk.Button.new_from_icon_name('window-close-symbolic', Gtk.IconSize.MENU)
            close.set_tooltip_text('Close')
            close.connect('clicked', lambda button: window.destroy())
            header.pack_end(close, False, False, 0)
            content.pack_start(header, False, False, 4)
            folder = folder_path(kind)
            try:
                files = recent_files(folder)
                empty_text = 'No completed files yet.'
            except OSError as error:
                files = []
                empty_text = 'Cannot read this folder.'
                print('Ember: ' + str(error), file=sys.stderr)
            for path, metadata in files:
                content.pack_start(self.file_row(path, metadata), False, False, 0)
            if not files:
                empty = Gtk.Label(label=empty_text, xalign=0)
                empty.set_margin_top(18)
                empty.set_margin_bottom(18)
                content.pack_start(empty, False, False, 0)
            footer = Gtk.Box(spacing=8)
            hint = Gtk.Label(label='Drag to attach · click to open', xalign=0)
            hint.get_style_context().add_class('file-detail')
            footer.pack_start(hint, True, True, 0)
            open_folder = Gtk.Button(label='Open folder')
            open_folder.connect('clicked', lambda button: self.open_path(folder))
            footer.pack_end(open_folder, False, False, 0)
            content.pack_start(footer, False, False, 8)
            window.show_all()
            window.present()

        def file_row(self, path, metadata):
            row = Gtk.EventBox()
            row.get_style_context().add_class('file-row')
            row.set_tooltip_text(os.fsdecode(os.fsencode(path)).encode('utf-8', 'replace').decode())
            row.dragged = False
            box = Gtk.Box(spacing=12)
            box.set_border_width(10)
            row.add(box)
            display_name = path.name.encode('utf-8', 'replace').decode()
            content_type, _ = Gio.content_type_guess(display_name, None)
            icon = Gio.content_type_get_icon(content_type or 'application/octet-stream')
            box.pack_start(Gtk.Image.new_from_gicon(icon, Gtk.IconSize.LARGE_TOOLBAR), False, False, 0)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            name = Gtk.Label(label=display_name, xalign=0)
            name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            name.set_max_width_chars(40)
            text.pack_start(name, False, False, 0)
            size = f'{metadata.st_size / 1024:.0f} KB' if metadata.st_size < 1024**2 else f'{metadata.st_size / 1024**2:.1f} MB'
            detail = Gtk.Label(label=datetime.fromtimestamp(metadata.st_mtime).strftime('%d %b %H:%M') + ' · ' + size, xalign=0)
            detail.get_style_context().add_class('file-detail')
            text.pack_start(detail, False, False, 0)
            box.pack_start(text, True, True, 0)
            # Copy-only, standard file URI payload; never delete/move the source.
            row.drag_source_set(Gdk.ModifierType.BUTTON1_MASK,
                                [Gtk.TargetEntry.new('text/uri-list', 0, 0)], Gdk.DragAction.COPY)
            row.drag_source_set_icon_gicon(icon)
            row.connect('drag-data-get', lambda widget, context, selection, info, timestamp: selection.set_uris([file_uri(path)]))
            row.connect('drag-begin', self.on_drag_begin)
            row.connect('drag-end', self.on_drag_end)
            row.connect('button-press-event', self.on_press)
            row.connect('button-release-event', lambda widget, event: self.on_release(widget, event, path))
            return row

        def on_press(self, row, event):
            if event.button == 1:
                row.dragged = False
            return False

        def on_release(self, row, event, path):
            if event.button == 1 and not row.dragged:
                self.open_path(path)
            return False

        def on_drag_begin(self, row, context):
            row.dragged = True
            self.dragging = True

        def on_drag_end(self, row, context):
            self.dragging = False
            # Keep the source alive until GTK has completed the transfer.
            GLib.idle_add(self.close_window)

        def close_window(self):
            if self.window is not None:
                self.window.destroy()
            return GLib.SOURCE_REMOVE

        def open_path(self, path):
            try:
                if path == folder_path(kind):
                    # Only an explicit Open folder click creates a missing folder.
                    path.mkdir(parents=True, exist_ok=True)
                Gio.AppInfo.launch_default_for_uri(file_uri(path), None)
            except (GLib.Error, OSError) as error:
                self.error_dialog = True
                dialog = Gtk.MessageDialog(transient_for=self.window, modal=True,
                    message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.CLOSE,
                    text='Could not open this item')
                dialog.format_secondary_text(str(error))
                dialog.run()
                dialog.destroy()
                self.error_dialog = False
                return
            self.close_window()

        def on_focus_out(self, window, event):
            def check():
                if self.window is not None and not self.dragging and not self.error_dialog and not self.window.is_active():
                    self.close_window()
                return GLib.SOURCE_REMOVE
            GLib.timeout_add(150, check)
            return False

        def on_key(self, window, event):
            if event.keyval == Gdk.KEY_Escape:
                self.close_window()
                return True
            return False

        def on_destroy(self, window):
            self.window = None

    return Popup().run([sys.argv[0]])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', choices=FOLDERS)
    parser.add_argument('--list', action='store_true', help='list the five files without a GUI')
    args = parser.parse_args()
    try:
        if args.list:
            print(json.dumps([file_uri(path) for path, _ in recent_files(folder_path(args.folder))]))
            return 0
        return run_popup(args.folder)
    except (ImportError, ValueError, OSError) as error:
        parser.exit(1, f'firehawk-files: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
