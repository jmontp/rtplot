# Dropdown display filtering

Browser capability: `dropdown_filter_v1`.

An application can narrow the displayed options of a declared dropdown without
rebuilding plots or changing its selected value:

```python
client.set_dropdown_filter('model', ['candidate_a', 'candidate_b'])
```

Equivalently, set `controls.model.visible_options` through `set_ui_state()`.

The list must be a unique subset of the originally declared string values.
An empty list is valid. The confirmed current value always remains visible;
when excluded, its label gains “(current · outside filter).” Application-driven
value updates also preserve the new selection. No control event is emitted by
filtering. Set `visible_options` to `None` to restore all declared choices.
State is revisioned and restored through the existing reconnect protocol.

This is a presentation filter, not an authorization rule: the declaration and
server value registry retain the complete options. Applications enforce any
selection policy they require. Other controls, stream buffers, and controller
settings are unaffected.
