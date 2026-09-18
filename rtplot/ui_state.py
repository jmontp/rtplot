"""Shared validation and sparse presentation-state merging (no I/O)."""
from copy import deepcopy

META_KEY = "__rtplot_view__"
CAPABILITIES = ["sections", "ui_state_v1", "presentation_v1"]
CONTROL_DEFAULTS = {"enabled": True, "visible": True, "busy": False, "selected": False, "reason": ""}
SECTION_DEFAULTS = {"visible": True, "status": "idle", "message": ""}
STATUSES = {"idle", "ready", "busy", "complete", "warning", "error"}


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
            if not isinstance(values, dict) or set(values) - set(defaults):
                raise ValueError(f"Unsupported properties for {group}.{ident}")
            merged = dict(target.get(ident, {}))
            for key, value in values.items():
                if value is None:
                    merged.pop(key, None)
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
