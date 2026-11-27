import React, { useEffect, useState } from 'react';
import { api } from './data/evaluation.js';

export default function ValidationInput({ onAnalyze, busy, error }) {
  const [routes, setRoutes] = useState([]);
  const [selected, setSelected] = useState('');
  const [ids, setIds] = useState('');
  const [period, setPeriod] = useState('11시~17시');
  const [day, setDay] = useState('weekday');
  const [loadError, setLoadError] = useState('');
  useEffect(() => {
    let live = true;
    api('/api/routes').then(data => {
      if (!live) return;
      setRoutes(data.routes);
      setSelected(data.routes[0]?.id || '');
      setIds(data.routes[0]?.link_ids.join(', ') || '');
    }).catch(e => { if (live) setLoadError(e.message); });
    return () => { live = false; };
  }, []);
  return <form className="validation-input" onSubmit={event => {
    event.preventDefault();
    const link_ids = ids.split(/[\s,]+/).filter(Boolean);
    onAnalyze({ link_ids, period, day_type: day });
  }}>
    <h2>실제 데이터로 평가 체험</h2>
    <p>길찾기 미연동 단계입니다. 위 방문지 입력과 별개로, 연결된 도로 ID의 검증용 경로를 평가합니다.</p>
    <label>검증용 경로<select value={selected} onChange={e => {
      setSelected(e.target.value);
      const route = routes.find(r => r.id === e.target.value);
      if (route) setIds(route.link_ids.join(', '));
    }}><option value="">직접 도로 ID 입력</option>{routes.map(route => <option key={route.id} value={route.id}>{route.name}</option>)}</select></label>
    <label>주행 순서의 도로 ID<textarea rows="3" required value={ids} onChange={e => { setIds(e.target.value); setSelected(''); }} placeholder="쉼표 또는 줄바꿈으로 구분"/></label>
    <div className="period-controls"><label>대표 시간대<select value={period} onChange={e => setPeriod(e.target.value)}>{['4시~10시', '11시~17시', '18시~24시'].map(p => <option key={p}>{p}</option>)}</select></label><label>요일<select value={day} onChange={e => setDay(e.target.value)}><option value="weekday">평일 통계</option><option value="weekend">주말 · 교통 미평가</option></select></label></div>
    {(error || loadError) && <p role="alert" className="evaluation-error">{error || loadError}</p>}
    <button className="button primary analyze" disabled={busy || !ids.trim()}>{busy ? '실제 도로 데이터 평가 중…' : '검증용 경로 평가 시작 →'}</button>
    <small>자동 교차로 추정 · 임시 0~100점 · 실제 통행 가능 경로를 보장하지 않습니다.</small>
  </form>;
}
