const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../user_tools/workbench/web/capacity.js'),'utf8');
const capacity=vm.runInNewContext(source+';({capacitySplit,capacityMetrics,capacityNearest})');

test('split counts actual sparse observations, rather than inventing missing cycles',()=>{
 const cell={cycles:[1,3,8,12],first:1,last:12};
 const split=capacity.capacitySplit(cell,5,2);
 assert.equal(split.train,2);assert.equal(split.held,2);assert.equal(split.future,2);assert.equal(split.valid,true);
 assert.equal(capacity.capacitySplit(cell,1,10).valid,false);
 assert.equal(capacity.capacitySplit(cell,12,0).valid,false);
 assert.equal(capacity.capacitySplit(cell,12,1).valid,true);
});
test('baseline comparison does not manufacture a percent when the baseline is zero',()=>{
 assert.equal(capacity.capacityMetrics({metrics:{mae_Ah:.2,rmse_Ah:.3,baseline_mae_Ah:0}}).improvement,null);
 assert.equal(capacity.capacityMetrics({metrics:null}).mae,null);
 assert.equal(capacity.capacityMetrics({metrics:{mae_Ah:.1,baseline_mae_Ah:.2}}).improvement,50);
 assert.equal(capacity.capacityMetrics({metrics:{mae_Ah:.3,baseline_mae_Ah:.2}}).improvement<0,true);
});
test('chart inspection selects a real recorded or forecast point on irregular axes',()=>{
 const points=[[1],[3],[8],[12]];
 assert.equal(capacity.capacityNearest(points,-10),0);
 assert.equal(capacity.capacityNearest(points,20),3);
 assert.equal(capacity.capacityNearest(points,6.9),2);
 assert.equal(capacity.capacityNearest(points,4),1);
 assert.equal(capacity.capacityNearest([],3),-1);
});
