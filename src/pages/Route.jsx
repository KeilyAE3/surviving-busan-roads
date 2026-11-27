import React,{useEffect,useState} from 'react';
import KakaoMap,{searchPlaces,mapHelp} from '../map/KakaoMap.jsx';
const options=[['▥','난이도 우선','부담이 적은 길'],['◷','소요시간 우선','빠르게 가는 길'],['♧','초보자 추천','단순한 길']];
export default function Route({stops,setStops,option,setOption,devPanel,onRoute,busy,error}){
 const [period,setPeriod]=useState('11시~17시');
 const [day,setDay]=useState('weekday');
 const [query,setQuery]=useState(null);
 const [results,setResults]=useState(null);
 useEffect(()=>{
  if(!query)return;
  let live=true;
  searchPlaces(query.text).then(places=>{if(live)setResults({places})}).catch(e=>{
   if(live){console.warn('[Kakao 장소 검색]',e.message,mapHelp);setResults({error:e.message+' '+mapHelp})}
  });
  return()=>{live=false};
 },[query]);
 function closeSearch(){setQuery(null);setResults(null)}
 function update(id,values){setStops(previous=>previous.map(stop=>stop.id===id?{...stop,...values}:stop))}
 function move(from,to){closeSearch();setStops(previous=>{const next=[...previous];[next[from],next[to]]=[next[to],next[from]];return next})}
 return <main className="shell planner"><section className="card planning-panel"><span className="eyebrow">01　경로 설정</span><h1>경로 입력<span className="spark">✦</span></h1><p className="sub">부산 내 이동할 장소를 선택하고<br/>출발 전에 운전 난이도와 주의 포인트를 살펴보세요.</p>
  <div className="stops">{stops.map((stop,i)=>{
   const last=i===stops.length-1;
   const name=i===0?'출발지':last?'도착지':'경유지 '+i;
   return <div className="stop" key={stop.id}><div className="stop-label"><label htmlFor={'stop-'+stop.id}><i className={i===0?'green':last?'orange':'blue'}/>{name}</label><div className="order-buttons">{i>0&&<button type="button" aria-label={name+' 위로 이동'} onClick={()=>move(i,i-1)}>↑</button>}{!last&&<button type="button" aria-label={name+' 아래로 이동'} onClick={()=>move(i,i+1)}>↓</button>}{i>0&&!last&&<button type="button" aria-label={name+' 삭제'} onClick={()=>{closeSearch();setStops(previous=>previous.filter(s=>s.id!==stop.id))}}>×</button>}</div></div>
   <form className="place-field" onSubmit={event=>{event.preventDefault();if(stop.text.trim()){setResults(null);setQuery({id:stop.id,text:stop.text.trim()})}}}><input id={'stop-'+stop.id} placeholder="부산 장소명 입력" value={stop.text} onChange={e=>{closeSearch();update(stop.id,{text:e.target.value,place:null})}}/>{stop.text&&<button type="button" className="clear" aria-label={name+' 지우기'} onClick={()=>{closeSearch();update(stop.id,{text:'',place:null})}}>×</button>}<button className="search" type="submit" disabled={!stop.text.trim()}>검색</button></form>
   {query?.id===stop.id&&<div className="place-results" aria-label="장소 검색 결과">{!results?<p role="status">검색 중…</p>:results.error?<p role="status">{results.error}</p>:!results.places.length?<p role="status">부산 내 검색 결과가 없습니다.</p>:<ul>{results.places.map(place=><li key={place.id}><button type="button" onClick={()=>{update(stop.id,{text:place.place_name,place});closeSearch()}}><strong>{place.place_name}</strong><small>{place.road_address_name||place.address_name}</small></button></li>)}</ul>}</div>}
   </div>;
  })}</div>
  <div className="stop-actions"><button type="button" className="button secondary" disabled={stops.length>=6} onClick={()=>{closeSearch();setStops(previous=>[...previous.slice(0,-1),{id:Math.max(...previous.map(stop=>stop.id))+1,text:''},previous.at(-1)])}}>⊕ 경유지 추가 <small>({stops.length}/6)</small></button><button type="button" className="button secondary" onClick={()=>move(0,stops.length-1)}>⇄ 출발·도착 교환</button></div>
  <fieldset className="options" disabled><legend>⚙ 경로 옵션 · 추후 지원</legend><div>{options.map(([icon,title,desc],i)=><label key={title}><input type="radio" name="route-option" checked={i===option} onChange={()=>setOption(i)}/><span>{icon}</span><strong>{title}</strong><small>{desc}</small></label>)}</div></fieldset>
  <p className="sub">현재는 거리 기준 자체 탐색을 제공합니다.</p>
  <div className="traffic-choice"><label>교통 통계 <select value={day} onChange={e=>setDay(e.target.value)}><option value="weekday">2025 평일 대표 통계</option><option value="weekend">주말 · 교통 미평가</option></select></label><label>시간대 <select value={period} disabled={day==='weekend'} onChange={e=>setPeriod(e.target.value)}>{['4시~10시','11시~17시','18시~24시'].map(p=><option key={p}>{p}</option>)}</select></label></div>
  <a className="driving-tip" href="#/points"><strong>◈ 부산 운전 포인트</strong><small>교차로와 합류 구간에서 미리 진행 방향을 확인하세요.</small></a>
  <div className="routing-notice"><strong>선택한 방문 순서대로 탐색합니다.</strong><p>회전 제한과 차량 출입구 정보가 불완전한 실험 경로입니다. 실제 통행 허용을 보장하지 않으며 운전 안내용으로 사용하지 마세요.</p><button className="button primary analyze" disabled={busy||stops.some(s=>!s.place)} onClick={()=>onRoute({period,day_type:day})}>{busy?'도로망 탐색·평가 중…':'경로 탐색 및 분석 →'}</button>{error&&<p className="evaluation-error" role="alert">{error}</p>}</div>
  {devPanel}
 </section><KakaoMap stops={stops}/></main>;
}
