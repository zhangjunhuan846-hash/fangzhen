const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,'../user_tools/workbench/web/platform.js'),'utf8');
const flow = vm.runInNewContext(source+';({projectFacts,projectNext,projectGroup,hasEvaluation,resultNextActions})');
const project = {id:'A',tables:{samples:[{id:'one'}]},issues:[]};

test('completed computation remains distinct from validation', () => {
 const f=flow.projectFacts(project,[{id:'a',workspace:'A',mode:'forward',status:'completed',result:{predicted_capacity_Ah:4.4}}],[]);
 assert.equal(f.completed.length,1);
 assert.equal(f.evaluations.length,0);
 assert.equal(flow.projectNext(f).page,'validation');
});
test('project progress excludes jobs from a different project', () => {
 const f=flow.projectFacts(project,[{id:'other',workspace:'B',mode:'predict',status:'completed',result:{holdout_pass:true}}],[]);
 assert.equal(f.jobs.length,0);
 assert.equal(f.evaluations.length,0);
 assert.equal(flow.projectNext(f).page,'modeling');
});
test('failed validation is still an evaluation record without becoming a pass', () => {
 assert.equal(flow.hasEvaluation({mode:'predict',status:'completed',result:{holdout_pass:false}}),true);
 assert.equal(flow.hasEvaluation({mode:'predict',status:'failed',result:{holdout_pass:true}}),false);
});
test('partial actual feedback sends the researcher back to the experiment', () => {
 const f=flow.projectFacts(project,[],[{status:'partial',record:{capacity:300}}]);
 assert.equal(f.pending.length,1);
 assert.equal(f.measured.length,1);
 assert.equal(flow.projectNext(f).page,'feedback');
});
test('completed identification carries the exact parent to held-out prediction', () => {
 const actions=flow.resultNextActions({id:'frozen-fit',mode:'identify',status:'completed'});
 assert.equal(actions[0][0],'jobs');
 assert.equal(actions[0][2].mode,'predict');
 assert.equal(actions[0][2].parent,'frozen-fit');
 assert.equal(flow.projectGroup('ml'),'modeling');
 assert.equal(flow.projectGroup('research'),'feedback');
 assert.equal(flow.projectGroup('research',{researchKind:'public'}),'validation');
 assert.equal(flow.projectGroup('jobs',{jobMode:'predict'}),'validation');
});
