import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const XML = `<node><interface name="local.nolan.DesktopBootstrap">
  <method name="Arm"><arg type="s" direction="in"/><arg type="u" direction="in"/></method>
  <method name="Status"><arg type="s" direction="out"/></method>
  <method name="Cancel"/>
</interface></node>`;

export default class DesktopBootstrap extends Extension {
    enable() {
        this._timer = 0;
        this._status = 'idle';
        this._dbus = Gio.DBusExportedObject.wrapJSObject(XML, this);
        this._dbus.export(Gio.DBus.session, '/local/nolan/DesktopBootstrap');
    }

    disable() {
        this.Cancel();
        this._dbus?.unexport();
        this._dbus = null;
    }

    Status() { return this._status; }

    Cancel() {
        if (this._timer)
            GLib.Source.remove(this._timer);
        this._timer = 0;
        this._status = 'idle';
    }

    Arm(kind, workspace) {
        const patterns = {
            terminal: /gnome-terminal/i,
            cursor: /cursor/i,
            brave: /brave/i,
        };
        const custom = kind.startsWith('window:') ? kind.slice(7).toLowerCase() : '';
        if ((!patterns[kind] && !custom) || workspace >= global.workspace_manager.n_workspaces)
            throw new Error('Unknown application or missing workspace');
        if (this._timer)
            throw new Error('Another window placement is pending');
        const existing = new Set(global.get_window_actors().map(a => a.meta_window));
        const deadline = GLib.get_monotonic_time() + 45000000;
        this._status = 'waiting';
        this._timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 100, () => {
            for (const actor of global.get_window_actors()) {
                const win = actor.meta_window;
                if (existing.has(win) || win.get_window_type() !== Meta.WindowType.NORMAL)
                    continue;
                const identity = `${win.get_wm_class() ?? ''} ${win.get_gtk_application_id() ?? ''}`;
                if (!(custom ? identity.toLowerCase().includes(custom) : patterns[kind].test(identity)))
                    continue;
                win.change_workspace_by_index(workspace, false);
                this._status = win.get_workspace().index() === workspace ? 'placed' : 'failed';
                this._timer = 0;
                return GLib.SOURCE_REMOVE;
            }
            if (GLib.get_monotonic_time() >= deadline) {
                this._status = 'timeout';
                this._timer = 0;
                return GLib.SOURCE_REMOVE;
            }
            return GLib.SOURCE_CONTINUE;
        });
    }
}
