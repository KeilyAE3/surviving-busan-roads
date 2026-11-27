import React, { useEffect, useRef, useState } from 'react';
import { api } from '../data/evaluation.js';
import { detailGroups, describe, publicLocation, scoreText } from '../data/presentation.js';
import KakaoMap from '../map/KakaoMap.jsx';

function RouteShape({ lines }) {
  const points = lines.flat();
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const [x, y] of points) {
    minX = Math.min(minX, x); minY = Math.min(minY, y);
    maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
  }
  const spanX = maxX-minX, spanY = maxY-minY;
  const ratio = Math.cos((minY+spanY/2)*Math.PI/180);
  const scale = Math.min(420/Math.max(spanX*ratio, .000001), 240/Math.max(spanY, .000001));
  const project = p => [40+(p[0]-minX)*ratio*scale+(420-spanX*ratio*scale)/2,
    280-(p[1]-minY)*scale-(240-spanY*scale)/2];
  const start = project(points[0]), end = project(points.at(-1));
  return <svg className="actual-route-shape" viewBox="0 0 500 320" role="img" aria-label="평가 구간의 도로 모양">
    <defs><pattern id="route-grid" width="25" height="25" patternUnits="userSpaceOnUse"><path d="M25 0H0V25" stroke="#c4dced" fill="none"/></pattern></defs>
    <rect width="500" height="320" fill="#eaf4fb"/><rect width="500" height="320" fill="url(#route-grid)"/>
    {lines.map((line, i) => <polyline key={i} points={line.map(project).map(p => p.join(',')).join(' ')} fill="none" stroke="#168deb" strokeWidth="6" strokeLinejoin="round" strokeLinecap="round"/>)}
    <circle cx={start[0]} cy={start[1]} r="8" fill="#009781" stroke="white" strokeWidth="3"/>
    <circle cx={end[0]} cy={end[1]} r="8" fill="#ed6228" stroke="white" strokeWidth="3"/>
  </svg>;
}

function Bar({ label, score }) {
  return score === null ? <div className="unrated-bar">미평가 · 정보 부족</div>
    : <div className="ability-track" role="meter" aria-label={label} aria-valuemin="0" aria-valuemax="100" aria-valuenow={score}><span style={{width:score+'%'}}/></div>;
}

export default function Result({ analysis, analysisRequest, devPanel }) {
  const [explanation, setExplanation] = useState(null);
  const [explaining, setExplaining] = useState(false);
  const [explainError, setExplainError] = useState('');
  const latestAnalysis = useRef(analysis);
  latestAnalysis.current = analysis;
  useEffect(() => { setExplanation(analysis?.explanation || null); setExplainError(''); }, [analysis]);
  const groups = detailGroups(analysis);
  async function requestExplanation() {
    const requestedAnalysis = analysis;
    setExplaining(true); setExplainError('');
    try {
      const next = await api('/api/explain', analysisRequest);
      if (latestAnalysis.current === requestedAnalysis) setExplanation(next);
    } catch { if (latestAnalysis.current === requestedAnalysis) setExplainError('AI 해설 연결을 아직 사용할 수 없습니다. 현재 근거 안내를 확인해 주세요.'); }
    finally { setExplaining(false); }
  }
  return <main className="result"><section className="result-banner"><div className="shell">
    <span className="eyebrow">◈ 경로 난이도 안내</span><h1>가장 주의할 상황을 미리 살펴보세요.</h1>
    <p><b className="demo-label">임시 평가 기준</b> 자체 도로망 탐색 결과를 분석합니다. 실제 통행 가능 여부가 검증된 자동차 경로는 아닙니다.</p>
  </div></section><div className="shell result-body">
    {!analysis ? <section className="card result-empty"><h2>분석할 이동 경로가 아직 없습니다.</h2><p>지도에서 방문할 장소를 선택하고 경로를 분석하세요.</p><a className="button primary" href="#/route">지도에서 장소 찾기 →</a></section> : <>
      <section className="card summary real-summary"><div><span>◈ 평가 구간</span><strong>{(analysis.length_m/1000).toFixed(3)}km</strong><small>{analysis.day_type === 'weekday' ? '2025 평일 대표 통계 · '+analysis.period : '주말 · 교통 미평가'}</small><small>점수는 평가한 구간 중 가장 높은 값입니다.</small></div>
        {analysis.categories.map(category => <div key={category.name}><span>{category.name}</span><strong className={category.score === null ? 'unrated' : ''}>{scoreText(category.score)}</strong><small>{category.score === null ? '자료가 없어 판단하지 않았습니다.' : '가장 주의할 상황의 임시 점수'}</small></div>)}
      </section>
      <p className="coverage-note">교통 혼잡 정보 확인 범위 {analysis.coverage.traffic_length_pct}% · 미수록 구간은 한산한 구간이 아닌 미평가 구간입니다.</p>
      {analysis.routing&&<aside className="card route-caution"><strong>{analysis.routing.places.map(p=>p.name).join(' → ')}</strong><p>도로망 탐색 {(analysis.routing.search_ms/1000).toFixed(2)}초 · 장소와 도로 사이 거리 {analysis.routing.snaps.map(s=>Math.round(s.distance_m)+'m').join(' / ')}</p>{analysis.routing.warnings.map(w=><p key={w}>{w}</p>)}</aside>}
      <div className="result-grid"><section className="card result-map"><h2>◈ 평가 구간 위치</h2>{analysis.routing?<KakaoMap stops={analysis.routing.places.map((p,i)=>({id:i,place:{place_name:p.name,x:p.lon,y:p.lat}}))} lines={analysis.route_geometry}/>:<RouteShape lines={analysis.route_geometry}/>}<p>자체 탐색 참고 경로입니다. 실제 운전 전 공식 길찾기와 도로 표지를 확인하세요.</p></section>
        <section className="card ability-chart"><h2>운전 능력별 난이도</h2><p>0~100점 · 높을수록 대응 부담이 큽니다.</p>{analysis.categories.map(category => <div className="ability-row" key={category.name}><div><strong>{category.name}</strong><b>{scoreText(category.score)}</b></div><Bar label={category.name} score={category.score}/></div>)}</section>
        <section className="card ai"><h2>✦ 주의사항과 준비</h2>{explanation && <><p className="ai-summary">{explanation.source === 'llm_grounded' ? 'AI가 중요 근거를 선택하고 확인된 내용으로 정리한 안내입니다.' : '확인된 평가 근거로 만든 안내입니다. AI가 생성한 해설은 아닙니다.'}</p>{explanation.empty && <p>평가한 범위에서 높은 점수의 주의 상황이 확인되지 않았습니다. 미평가 항목도 함께 확인하세요.</p>}{explanation.situations.map(item => {
          const row = analysis.details.find(r => r.id === item.id);
          const label = groups.flatMap(g => g.items).find(i => i.key === item.item || row?.kinds?.includes(i.key))?.label || '주의할 상황';
          return <div key={item.id}><h3>{label} · {scoreText(item.score)}</h3><p><b>{publicLocation(item.location)}</b><br/>{describe(row, analysis)}</p></div>;
        })}<h3>출발 전 준비</h3><ul className="preparations">{explanation.preparations.map(text => <li key={text}>{text}</li>)}</ul></>}
          <button type="button" className="button secondary" disabled={explaining} onClick={requestExplanation}>{explaining ? 'AI 해설 준비 중…' : 'AI 해설 요청'}</button>{explainError && <p role="alert" className="evaluation-error">{explainError}</p>}
        </section></div>
    </>}
    <section className="card detail-charts"><h2>상황별 난이도</h2><p>같은 항목이 여러 곳에 있으면 가장 높은 점수와 해당 위치를 표시합니다. 미평가는 0점과 다릅니다.</p>
      <div className="detail-groups">{groups.map(group => <section className="detail-group" key={group.category}><h3>{group.category}</h3>{group.items.map(item => <article className="detail-bar" key={item.key}><div className="detail-bar-heading"><strong>{item.label}</strong><b className={item.score === null ? 'unrated' : ''}>{scoreText(item.score)}</b></div><Bar label={item.label} score={item.score}/><p>{item.score !== null && <b>{item.location} · </b>}{item.description}</p>{item.partiallyUnrated && <small>다른 구간 중 정보가 없는 곳은 평가에서 제외했습니다.</small>}</article>)}</section>)}</div>
    </section>
    {devPanel && <section className="card developer-tools">{devPanel}</section>}
  </div></main>;
}

