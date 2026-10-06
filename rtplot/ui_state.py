"""Shared validation and sparse presentation-state merging (no I/O)."""
from copy import deepcopy

META_KEY = "__rtplot_view__"
CAPABILITIES = ["sections", "ui_state_v1", "presentation_v1", "dropdown_v1", "xy_v1", "grid_picker_v1", "checkbox_v1"]
CONTROL_DEFAULTS = {"enabled": True, "visible": True, "busy": False, "selected": False, "reason": ""}
# Application-confirmed grid state rides in the same revisioned UI state as presentation.
GRID_STATE_KEYS = {"value", "active", "cells", "message", "request"}
GRID_CELL_DEFAULTS = {"enabled": True, "busy": False, "reason": "", "label": ""}
SECTION_DEFAULTS = {"visible": True, "status": "idle", "message": ""}
STATUSES = {"idle", "ready", "busy", "complete", "warning", "error"}


def _choices(options, name, nonempty=False):
    if not isinstance(options, list) or not options:
        raise ValueError(f"{name} options must be a non-empty list")
    choices = []
    for option in options:
        if isinstance(option, str):
            value, label = option, option
        elif isinstance(option, dict):
            value, label = option.get("value"), option.get("label", option.get("value"))
        else:
            raise ValueError(f"{name} options must be strings or value/label dictionaries")
        if not isinstance(value, str) or not isinstance(label, str) or (nonempty and not value):
            raise ValueError(f"{name} option values and labels must be strings"
                             + (" (values non-empty)" if nonempty else ""))
        if value in [v for v, _ in choices]:
            raise ValueError(f"{name} option values must be unique")
        choices.append((value, label))
    return choices


def dropdown_options(control):
    """Return validated (value, label) choices; values are always strings."""
    choices = _choices(control.get("options"), "Dropdown")
    if control.get("value", choices[0][0]) not in [v for v, _ in choices]:
        raise ValueError("Dropdown value must match an option")
    return choices


def grid_declaration(control):
    """Validate a grid picker and return its registry entry.

    Option IDs are unique per axis; y_options[0] is the bottom row. An omitted
    value confirms the first X and first Y option.
    """
    xs = [v for v, _ in _choices(control.get("x_options"), "Grid X", True)]
    ys = [v for v, _ in _choices(control.get("y_options"), "Grid Y", True)]
    for key in ("label", "x_label", "y_label"):
        if not isinstance(control.get(key, ""), str):
            raise ValueError(f"Grid {key} must be a string")
    value = control.get("value", {"x": xs[0], "y": ys[0]})
    if not isinstance(value, dict) or set(value) != {"x", "y"} or value["x"] not in xs or value["y"] not in ys:
        raise ValueError("Grid value must be {'x': <declared X>, 'y': <declared Y>}")
    if type(control.get("active", True)) is not bool:
        raise ValueError("Grid active must be boolean")
    return {"x_options": xs, "y_options": ys, "default": dict(value),
            "active": control.get("active", True)}


def grid_cells(cells, info):
    """Validate per-cell overrides shaped {x_id: {y_id: {enabled, busy, reason, label}}}."""
    if not isinstance(cells, dict):
        raise ValueError("Grid cells must be a map of X IDs to Y maps")
    for x, column in cells.items():
        if x not in info["x_options"] or not isinstance(column, dict):
            raise ValueError(f"Unknown grid X ID: {x}")
        for y, cell in column.items():
            if y not in info["y_options"]:
                raise ValueError(f"Unknown grid Y ID: {y}")
            if not isinstance(cell, dict) or set(cell) - set(GRID_CELL_DEFAULTS):
                raise ValueError("Grid cells support only enabled, busy, reason and label")
            for key, value in cell.items():
                if type(value) is not type(GRID_CELL_DEFAULTS[key]):
                    raise ValueError(f"Invalid type for grid cell {key}")
                if isinstance(value, str) and len(value) > 4096:
                    raise ValueError("Presentation strings must be at most 4096 characters")
    return cells


def grid_cell(state, cid, x, y):
    """Merged per-cell override for a grid in a UI state snapshot."""
    cells = state.get("controls", {}).get(cid, {}).get("cells", {})
    return {**GRID_CELL_DEFAULTS, **cells.get(x, {}).get(y, {})}


def _grid_property(key, value, info):
    if key == "value":
        if (not isinstance(value, dict) or set(value) != {"x", "y"}
                or value["x"] not in info["x_options"] or value["y"] not in info["y_options"]):
            raise ValueError("Grid value must name a declared X and Y")
    elif key == "active" and type(value) is not bool:
        raise ValueError("Grid active must be boolean")
    elif key == "cells":
        grid_cells(value, info)
    elif key in ("message", "request") and (not isinstance(value, str) or len(value) > 4096):
        raise ValueError(f"Grid {key} must be a string of at most 4096 characters")


def declarations(config, view=None):
    """Validate optional view and return normalized view plus control registry."""
    if hasattr(view, "to_dict"):
        view = view.to_dict()
    view = deepcopy(view or {})
    if not isinstance(view, dict):
        raise ValueError("view must be a dictionary or View")
    sections = view.get("sections", [])
    if not isinstance(sections, list):
        raise ValueError("view.sections must be a list")
    normalized, ids = [], set()
    for section in sections:
        if hasattr(section, "to_dict"):
            section = section.to_dict()
        if not isinstance(section, dict):
            raise ValueError("Each section must be a dictionary or Section")
        sid = section.get("id")
        if not isinstance(sid, str) or not sid or sid in ids:
            raise ValueError("Section IDs must be unique non-empty strings")
        ids.add(sid)
        s = {"id": sid, "title": sid, "description": "", "collapsible": False,
             "collapsed": False, "visible": True, "navigation": "primary", "density": "normal",
             "show_heading": True, **section}
        for key in ("title", "description"):
            if not isinstance(s[key], str):
                raise ValueError(f"Section {key} must be a string")
        for key in ("collapsible", "collapsed", "visible"):
            if not isinstance(s[key], bool):
                raise ValueError(f"Section {key} must be boolean")
        for key, default, allowed in (("navigation", "primary", {"primary", "secondary"}),
                                      ("density", "normal", {"normal", "compact"})):
            if s.get(key, default) not in allowed:
                raise ValueError(f"Invalid section {key}")
        if type(s.get("show_heading", True)) is not bool:
            raise ValueError("show_heading must be boolean")
        if not s["collapsible"]:
            s["collapsed"] = False
        normalized.append(s)
    persistent = view.get("persistent_section")
    if persistent is not None and persistent not in ids:
        raise ValueError("persistent_section must name a declared section")
    controls = {}
    for key, row in config.items():
        if key == META_KEY or "non_plot_labels" in row:
            continue
        sid = row.get("section")
        if sid is not None and sid not in ids:
            raise ValueError(f"Unknown section: {sid}")
        if sid == persistent and persistent is not None and "controls" not in row:
            raise ValueError("The persistent section can contain only control rows")
        if "plots" in row and any(p.get("section") is not None for p in row["plots"]):
            raise ValueError("Assign section on the PlotRow, not its child plots")
        if row.get("title") is not None and not isinstance(row["title"], str):
            raise ValueError("Control group title must be a string")
        if type(row.get("exclusive", False)) is not bool:
            raise ValueError("Control group exclusive must be boolean")
        for plot in row.get("plots", [row]):
            if "min_height" in plot and (type(plot["min_height"]) is not int or plot["min_height"] < 160):
                raise ValueError("Plot min_height must be an integer >= 160 CSS pixels")
        for control in row.get("controls", []):
            cid = control.get("id")
            if not isinstance(cid, str) or not cid:
                raise ValueError("Control IDs must be non-empty strings")
            if cid in controls:
                raise ValueError(f"Duplicate control ID: {cid}")
            if control.get("appearance", "default") not in {"default", "help", "state", "primary", "choice", "warning", "danger"}:
                raise ValueError("Unknown control appearance")
            if row.get("exclusive") and control.get("type") != "button":
                raise ValueError("Exclusive groups may contain only buttons")
            controls[cid] = {"type": control.get("type"), "section": sid}
            if control.get("type") == "dropdown":
                controls[cid]["options"] = [value for value, _ in dropdown_options(control)]
            elif control.get("type") == "grid_picker":
                controls[cid].update(grid_declaration(control))
            if row.get("exclusive"):
                controls[cid]["exclusive_group"] = key
    essentials = view.get("essential_controls", [])
    if not isinstance(essentials, list) or any(not isinstance(cid, str) or cid not in controls for cid in essentials):
        raise ValueError("essential_controls must list existing control IDs")
    if len(set(essentials)) != len(essentials):
        raise ValueError("essential_controls must not contain duplicate IDs")
    result = {"sections": normalized, "persistent_section": persistent} if view else {}
    if essentials:
        result["essential_controls"] = essentials
    return result, controls


def merge_state(current, patch, controls, view):
    """Apply a patch atomically. Null properties/targets remove overrides."""
    if not isinstance(patch, dict) or set(patch) - {"controls", "sections"}:
        raise ValueError("UI state must contain only controls and sections maps")
    result = deepcopy(current)
    selected_groups = {}
    for cid, values in patch.get("controls", {}).items() if isinstance(patch.get("controls", {}), dict) else []:
        group = controls.get(cid, {}).get("exclusive_group")
        if group and isinstance(values, dict) and values.get("selected") is True:
            if group in selected_groups:
                raise ValueError("An exclusive group may have only one selected choice")
            selected_groups[group] = cid
    for group, selected in selected_groups.items():
        for cid, info in controls.items():
            if cid != selected and info.get("exclusive_group") == group:
                result.setdefault("controls", {}).get(cid, {}).pop("selected", None)
                if not result["controls"].get(cid):
                    result["controls"].pop(cid, None)
    section_ids = {s["id"] for s in view.get("sections", [])}
    for group, changes in patch.items():
        if not isinstance(changes, dict):
            raise ValueError(f"UI state {group} must be a map")
        defaults = CONTROL_DEFAULTS if group == "controls" else SECTION_DEFAULTS
        known = controls if group == "controls" else section_ids
        target = result.setdefault(group, {})
        for ident, values in changes.items():
            if ident not in known:
                raise ValueError(f"Unknown {group} ID: {ident}")
            if values is None:
                target.pop(ident, None)
                continue
            grid = controls[ident] if group == "controls" and controls[ident].get("type") == "grid_picker" else None
            allowed = set(defaults) | (GRID_STATE_KEYS if grid else set())
            if not isinstance(values, dict) or set(values) - allowed:
                raise ValueError(f"Unsupported properties for {group}.{ident}")
            merged = dict(target.get(ident, {}))
            for key, value in values.items():
                if value is None:
                    merged.pop(key, None)
                    continue
                if key in GRID_STATE_KEYS:
                    _grid_property(key, value, grid)
                    merged[key] = deepcopy(value)
                    continue
                if type(value) is not type(defaults[key]):
                    raise ValueError(f"Invalid type for {group}.{ident}.{key}")
                if key == "status" and value not in STATUSES:
                    raise ValueError(f"Unknown section status: {value}")
                if isinstance(value, str) and len(value) > 4096:
                    raise ValueError("Presentation strings must be at most 4096 characters")
                merged[key] = value
            if merged:
                target[ident] = merged
            else:
                target.pop(ident, None)
    return result


def presentation_requested(config, view):
    """Whether a layout relies on options introduced in presentation_v1."""
    if view.get("essential_controls"):
        return True
    if any(s.get("navigation", "primary") != "primary" or s.get("density", "normal") != "normal"
           or not s.get("show_heading", True) for s in view.get("sections", [])):
        return True
    for key, row in config.items():
        if key == META_KEY:
            continue
        if row.get("title") and "controls" in row or row.get("exclusive"):
            return True
        if any(c.get("appearance", "default") != "default" for c in row.get("controls", [])):
            return True
        for plot in row.get("plots", [row]):
            if plot.get("min_height") or any(style in ("dashed", "dotted", "dashdot") for style in (plot.get("line_style") or [])):
                return True
    return False
