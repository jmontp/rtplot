/* Presentation-only subset: preserve the confirmed selection and emit no input. */
(function (root) {
  function filterChoices(choices, visible, current) {
    const allowed = visible == null ? null : new Set(visible);
    return choices.filter(c => !allowed || allowed.has(c.value) || c.value === current)
      .map(c => ({...c, label: allowed && !allowed.has(c.value) && c.value === current
        ? c.label + ' (current · outside filter)' : c.label}));
  }
  root.rtplotFilterDropdownChoices = filterChoices;
  if (typeof module !== 'undefined') module.exports = filterChoices;
})(typeof window !== 'undefined' ? window : globalThis);
