import { strict as assert } from 'node:assert';
import { moveBox, resizeBox, mmToFraction, fractionToMm, setDimensionMm, overlappingPairs } from '../src/lib/report-layout-geometry';
import type { Box, Page, Handle } from '../src/lib/report-layout-geometry';
const box: Box={ field:'subject_name',x:.2,y:.3,width:.3,height:.1,font_size:12 };
const page: Page={ image:'',width_pt:595.28,height_pt:841.89,boxes:[box] };
const free={ snap:false,gridMm:0,toleranceX:.01,toleranceY:.01 };
const near=(a: number,b: number) => assert.ok(Math.abs(a-b)<1e-8,`${a} != ${b}`);
near(fractionToMm(mmToFraction(35.7,page.width_pt),page.width_pt),35.7);
const moved=moveBox(box,2,-2,page,[],free).box;
near(moved.x,.7); near(moved.y,0); near(moved.width,box.width);
const target={ ...box,x:.6,y:.6,width:.2 };
const zoomed=moveBox(box,.095,.02,page,[target],{ ...free,snap:true,toleranceX:.001 });
near(zoomed.box.x,.295); // A distant edge must not snap when highly zoomed.
const aligned=moveBox(box,.098,.297,page,[target],{ ...free,snap:true });
near(aligned.box.x+box.width,.6); near(aligned.guides.x!,.6);
near(aligned.box.y,.6); assert.ok([aligned.box.y,aligned.box.y+box.height/2,aligned.box.y+box.height].some(y => Math.abs(y-aligned.guides.y!)<1e-8));
const grid=moveBox(box,.013,.017,page,[],{ ...free,snap:true,gridMm:5,toleranceX:0,toleranceY:0 }).box;
const gridUnits=fractionToMm(grid.x,page.width_pt)/5;
near(gridUnits,Math.round(gridUnits));
const resized=resizeBox(box,'nw',-.1,-.1,page,[],free).box;
near(resized.x,.1); near(resized.x+resized.width,.5); near(resized.y+resized.height,.4);
for (const handle of ['n','ne','e','se','s','sw','w','nw'] as Handle[]) {
  for (const delta of [-3,3]) {
    const result=resizeBox(box,handle,delta,delta,page,[],free).box;
    assert.ok(result.x>=0 && result.y>=0 && result.x+result.width<=1.000001 && result.y+result.height<=1.000001);
    assert.ok(result.width>0 && result.height>0);
  }
}
const precise=setDimensionMm(box,'width',42.3,page);
near(fractionToMm(precise.width,page.width_pt),42.3); near(precise.x,box.x);
const position=setDimensionMm(box,'x',1000,page);
near(position.x,1-box.width); near(position.width,box.width);
assert.deepEqual(setDimensionMm(box,'width',NaN,page),box);
const narrow=setDimensionMm({ ...box,x:.999,width:.001 },'width',2,page);
assert.ok(narrow.x+narrow.width<=1 && narrow.width>0);
assert.deepEqual(overlappingPairs([box,{ ...box,x:.4 },{ ...box,y:.7 }]),[[0,1]]);
assert.deepEqual(overlappingPairs([box,{ ...box,x:.5 }]),[]);
console.log('Template geometry: physical units, snapping, page bounds, eight resize handles, and overlap checks passed.');
