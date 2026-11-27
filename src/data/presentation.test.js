import { test } from 'node:test';
import assert from 'node:assert/strict';
import { detailGroups, publicLocation, describe } from './presentation.js';

test('same item uses highest score without changing input; null and zero differ', () => {
  const result = { details: [
    { category:'도로주행 능력', item:'차로 수 감소',score:20,ratio:.2,location:'첫 지점' },
    { category:'도로주행 능력', item:'차로 수 감소',score:70,ratio:.7,location:'둘째 지점' },
    { category:'도로주행 능력', item:'차로 수 감소',score:null,location:'미수록 지점' },
    { category:'도로주행 능력', item:'회전',score:0,angle_deg:0,location:'직진 지점' }
  ] };
  const before = JSON.stringify(result);
  const groups = detailGroups(result);
  assert.deepEqual(groups.map(g=>g.category),['도로주행 능력','연속 상황 대응','교통 상황 대응']);
  assert.equal(groups[0].items[0].score,70);
  assert.equal(groups[0].items[0].location,'둘째 지점');
  assert.equal(groups[0].items[0].partiallyUnrated,true);
  assert.equal(groups[0].items[1].score,0);
  assert.equal(groups[2].items[0].score,null);
  assert.equal(JSON.stringify(result),before);
});
test('continuous labels are adjacent and source evidence is never exposed verbatim',()=>{
  const result={details:[{category:'연속 상황 대응',item:'combined',kinds:['좌회전 후 우회전','회전 후 차로 수 감소'],score:60,gap_m:50,block_length_m:70,location:'교차로',evidence:'internal_link_id 1234567890'}]};
  const group=detailGroups(result)[1];
  assert.equal(group.items[0].score,60);
  assert.equal(group.items[3].score,60);
  assert.equal(group.items[5].score,null);
  assert.ok(!describe(result.details[0],result).includes('internal_link_id'));
  assert.ok(!publicLocation('교차 지점 1234567890').includes('1234567890'));
});
