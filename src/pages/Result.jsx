import React from 'react';
import demo from '../data/demo.js';
import {Schematic} from './Home.jsx';
const x=i=>83+i*96;
const y=score=>142-score*1.15;
function Charts(){
 const points=demo.segments.map(([,score],i)=>x(i)+','+y(score)).join(' ');
 const total=demo.types.reduce((sum,[,n])=>sum+n,0);
 let offset=0;
 const gradient=demo.types.filter(([,n])=>n).map(([,n,color])=>{const start=offset;offset+=n/total*100;return color+' '+start+'% '+offset+'%'}).join(',');
 return <section className="card chart-box"><h2>▥ 구간별 운전 난이도</h2><svg className="chart" viewBox="0 0 455 162" role="img" aria-label={demo.segments.map(([name,score])=>name+' '+score+'점').join(', ')}>
  {[0,20,40,60,80,100].map(t=><g key={t}><line x1="34" x2="424" y1={y(t)} y2={y(t)} stroke="#dce6f3"/><text x="26" y={y(t)+4} textAnchor="end">{t}</text></g>)}
  {demo.segments.map(([name,score],i)=><rect key={name} x={x(i)-28} y={y(score)} width="56" height={142-y(score)} rx="6" fill={score===Math.max(...demo.segments.map(s=>s[1]))?'#ffbf82':'#9dd9fa'}/>)}
  <polyline fill="none" stroke="#0868d7" strokeWidth="2.5" points={points}/>
  {demo.segments.map(([name,score],i)=><g key={name}><circle cx={x(i)} cy={y(score)} r="4" fill="white" stroke="#0868d7" strokeWidth="2"/><text x={x(i)} y={y(score)-9} textAnchor="middle" fontWeight="bold">{score}</text><text x={x(i)} y="158" textAnchor="middle">구간 {i+1}</text></g>)}
 </svg><ol className="segments">{demo.segments.map(([name])=><li key={name}>{name}</li>)}</ol>
 <h3>난이도 유형별 구간 수</h3><div className="type-chart"><div className="donut" aria-hidden="true" style={{background:'conic-gradient('+gradient+')'}}><span>총<br/><b>{total}구간</b></span></div><ul>{demo.types.map(([name,count,color])=><li key={name}><i style={{background:color}}/>{name}<b>{count}구간 ({count/total*100}%)</b></li>)}</ul></div></section>;
}
export default function Result(){
 return <main className="result"><section className="result-banner"><div className="shell"><span className="eyebrow">◈ 경로 분석 결과</span><h1>선택한 경로의 운전 난이도 분석 결과예요!</h1><p><b className="demo-label">디자인 시연용 예시 데이터</b> 입력한 장소를 분석한 결과가 아닙니다.</p></div></section>
 <div className="shell result-body"><section className="card summary"><div><span>◈ 분석한 경로</span><strong>{demo.route}</strong><small>약 {demo.km}km · 주요 경유: {demo.via}</small></div><div><span>▥ 전체 예상 운전 난이도</span><div className="score"><b>{demo.grade}</b><strong>{demo.score}<small> /100점</small></strong></div></div><div><span>◷ 총 예상 소요 시간</span><strong>약 {demo.minutes}분</strong></div><div><span>▲ 주요 주의 포인트</span><div className="tags">{demo.tags.map(tag=><b key={tag}>{tag}</b>)}</div></div></section>
 <div className="result-grid"><section className="card result-map"><h2>◈ 경로 지도 <small>(예시)</small></h2><Schematic result/><p>개념도 · 실제 자동차 이동 경로 아님</p><div className="legend result-legend"><span><i className="blue"/>원활</span><span><i className="orange"/>주의</span><span><i className="red"/>어려움</span></div></section>
 <Charts/><section className="card ai"><h2>✦ AI 주행 설명 <small>(예시)</small></h2><p className="ai-summary">{demo.summary}</p>{demo.notes.map(([title,note])=><div key={title}><h3>{title}</h3><p>{note}</p></div>)}</section></div>
 <section className="card comparison"><div><h2>↪ 경로 비교</h2><p>예시 경로의 난이도,<br/>시간과 거리를 비교해 보세요.</p><a className="button secondary" href="#/route">← 경로 다시 입력</a></div>{demo.comparison.map((item,i)=><article key={item.label} className={i===0?'recommended':''}><span className="eyebrow">{i===0?'★':'○'} {item.label}</span><h3>{item.route}</h3><div className="metrics"><span>예상 난이도<b>{item.grade} ({item.score}점)</b></span><span>예상 시간<b>{item.minutes}분</b></span><span>거리<b>{item.km}km</b></span></div><p>{item.note}</p></article>)}</section></div></main>;
}
