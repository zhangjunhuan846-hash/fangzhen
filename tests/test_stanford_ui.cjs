const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
let downloaded;
const sandbox = {
  esc: value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  download: (body,name,type) => { downloaded = {body,name,type}; },
  lineChart: () => '<svg role="img"></svg>',
  console,
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('user_tools/workbench/web/engineering.js','utf8'),sandbox);
const reportButton = {};
const root = {querySelectorAll: selector => selector === '[data-stanford-report]' ? [reportButton] : []};
const job = {result:{title:'W8 测试',source:'https://osf.io/qsabn/',metrics:{RMSE:14.7},
  details:{cell:'W8',diagnostic:'Diag_1',source_scope:'后续回合',dynamic_start:'start',dynamic_end:'end',
    eis_screening:'未使用',scope:'开环',model_sha256:'abc',selection_sha256:'def'}},
  curves:[{name:'电压',points:[[0,3.9,4],[1,3.8,3.9]]}]};
sandbox.engineeringDownloads(root,job); reportButton.onclick();
assert(downloaded.name.endsWith('.html'));
assert(downloaded.body.includes('Diag_1') && downloaded.body.includes('<svg') && downloaded.body.includes('14.7'));
console.log('Stanford report export UI: pass');
