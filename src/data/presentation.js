const definitions = [
  ['도로주행 능력', [
    ['차로 수 감소', '차로가 줄어드는 구간'], ['회전', '방향을 크게 바꾸는 회전'],
    ['교차로 갈래 수', '갈림길이 많은 교차로'], ['합류·분기', '차량이 합쳐지거나 나뉘는 구간']]],
  ['연속 상황 대응', [
    ['좌회전 후 우회전', '좌회전 뒤 곧 우회전'], ['우회전 후 좌회전', '우회전 뒤 곧 좌회전'],
    ['차로 수 감소 후 회전', '차로가 줄어든 뒤 회전'], ['회전 후 차로 수 감소', '회전한 뒤 차로가 줄어듦'],
    ['기타 어려운 상황 연속', '여러 주의 상황이 이어지는 구간'],
    ['실제 차로 변경 후 회전', '차로를 옮긴 뒤 회전']]],
  ['교통 상황 대응', [['과거 교통 상황', '평소 교통 혼잡에 대응']]]
];

export const scoreText = value => value === null ? '미평가' : value.toFixed(1) + '점';
export const publicLocation = value => value && value !== '-'
  ? value.replace(/\b\d{10,}\b/g, '도로 구간').replace('검증용 경로', '전체 경로') : '도로 구간';

export function describe(row, result) {
  if (!row || row.score === null) {
    if (row?.item === '실제 차로 변경 후 회전') return '차로를 옮겨야 하는 정확한 위치와 횟수 정보가 없어 평가하지 않았습니다.';
    if (row?.category === '교통 상황 대응') return '해당 요일 또는 도로의 비교 가능한 과거 교통정보가 부족합니다. 한산하다는 뜻은 아닙니다.';
    return '이 항목을 판단할 정보나 교차로 사이 구간이 충분하지 않습니다.';
  }
  if (row.item === '차로 수 감소') return '진입 도로에 비해 차로 수가 '+(row.ratio*100).toFixed(1)+'% 줄어드는 지점입니다. 실제 차로 변경 횟수를 뜻하지 않습니다.';
  if (row.item === '회전') return '진행 방향이 약 '+Math.abs(row.angle_deg).toFixed(1)+'도 바뀝니다. 같은 교차로 안의 이동은 한 번으로 보았습니다.';
  if (row.item === '교차로 갈래 수') return '서로 다른 도로 방향이 약 '+row.arms+'개로 추정됩니다. 같은 길의 진입·진출은 중복해서 세지 않았습니다.';
  if (row.item === '합류·분기') return row.merge || row.diverge
    ? '도로 연결상 차량이 '+[row.merge && '합쳐지는',row.diverge && '나뉘는'].filter(Boolean).join(' 또는 ')+' 구조가 추정됩니다. 실제 시설과 다를 수 있습니다.'
    : '현재 도로 연결정보에서 합류·분기 주의 후보가 확인되지 않았습니다.';
  if (row.category === '연속 상황 대응') return row.gap_m !== undefined
    ? '주의 상황 사이 거리는 약 '+row.gap_m.toFixed(0)+'m, 두 교차로 사이 구간은 약 '+row.block_length_m.toFixed(0)+'m입니다. 차로 변경 위치·횟수는 판단하지 않았습니다.'
    : '확인한 교차로 사이에서 짧은 거리의 연속 주의 상황이 나타나지 않았습니다.';
  const traffic = result?.traffic?.find(t => t.group_id === row.group_id && t.score !== null);
  return traffic ? '2025년 평일 '+result.period+' 평균속도 '+(traffic.speed ?? '정보 없음')+'km/h. 평일 전체 혼잡빈도 '+(traffic.frequency ?? '정보 없음')+'%, 혼잡시간 '+(traffic.congestion_time ?? '정보 없음')+'%를 함께 살펴보았습니다. 실시간 상황은 아닙니다.' : '과거 교통 통계를 바탕으로 평가했습니다.';
}

export function detailGroups(result) {
  const rows = result?.details || [];
  return definitions.map(([category, items]) => ({ category, items: items.map(([key, label]) => {
    let candidates = rows.filter(r => r.category === category && (r.item === key || r.kinds?.includes(key)));
    if (!candidates.length && category === '연속 상황 대응' && key !== '실제 차로 변경 후 회전') {
      candidates = rows.filter(r => r.category === category && r.item === '연속 상황');
    }
    const rated = candidates.filter(r => r.score !== null);
    const representative = rated.reduce((best, row) => !best || row.score > best.score ? row : best, null) || candidates[0];
    return { key, label, score: representative?.score ?? null, row: representative,
      count: candidates.length, partiallyUnrated: rated.length > 0 && rated.length < candidates.length,
      location: publicLocation(representative?.location), description: describe(representative, result) };
  }) }));
}
