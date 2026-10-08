const assert = require('node:assert/strict');
const filter = require('../rtplot/static/dropdown-filter.js');
const choices = [{value:'a', label:'A'}, {value:'b', label:'B'}, {value:'c', label:'C'}];
assert.deepEqual(filter(choices, ['b'], 'a'), [
  {value:'a', label:'A (current · outside filter)'}, {value:'b', label:'B'}]);
assert.deepEqual(filter(choices, [], 'c'), [{value:'c', label:'C (current · outside filter)'}]);
assert.deepEqual(filter(choices, null, 'a'), choices);
assert.deepEqual(filter(choices, ['b'], 'b'), [{value:'b', label:'B'}]);
