"""Shared validation and sparse presentation-state merging (no I/O)."""
from copy import deepcopy

META_KEY = "__rtplot_view__"
CAPABILITIES = ["sections", "ui_state_v1"]
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
             "collapsed": False, "visible": True, **section}
        for key in ("title", "description"):
            if not isinstance(s[key], str):
                raise ValueError(f"Section {key} must be a string")
        for key in ("collapsible", "collapsed", "visible"):
            if not isinstance(s[key], bool):
                raise ValueError(f"Section {key} must be boolean")
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
        for control in row.get("controls", []):
            cid = control.get("id")
            if not isinstance(cid, str) or not cid:
                raise ValueError("Control IDs must be non-empty strings")
            if cid in controls:
                raise ValueError(f"Duplicate control ID: {cid}")
            controls[cid] = {"type": control.get("type"), "section": sid}
    return ({"sections": normalized, "persistent_section": persistent} if view else {}), controls


def merge_state(current, patch, controls, view):
    """Apply a patch atomically. Null properties/targets remove overrides."""
    if not isinstance(patch, dict) or set(patch) - {"controls", "sections"}:
        raise ValueError("UI state must contain only controls and sections maps")
    result = deepcopy(current)
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
