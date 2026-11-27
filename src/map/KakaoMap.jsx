import React,{useEffect,useRef,useState} from 'react';
const key=import.meta.env.VITE_KAKAO_MAP_KEY?.trim();
const center=[35.165,129.12];
let pending;
const noLines=[];
function loadMaps(){
 if(!key) return Promise.reject(new Error('카카오 지도 키가 설정되지 않았습니다.'));
 if(window.kakao?.maps?.Map && window.kakao?.maps?.services) return Promise.resolve(window.kakao.maps);
 return pending??=new Promise((resolve,reject)=>{
  const script=document.createElement('script');
  const fail=()=>{script.remove();reject(new Error('카카오 지도 SDK를 불러오지 못했습니다.'));};
  const timer=setTimeout(fail,12000);
  script.src='https://dapi.kakao.com/v2/maps/sdk.js?'+new URLSearchParams({appkey:key,autoload:'false',libraries:'services'});
  script.onerror=()=>{clearTimeout(timer);fail()};
  script.onload=()=>{const maps=window.kakao?.maps;if(!maps?.load){clearTimeout(timer);fail();return}
    maps.load(()=>{clearTimeout(timer);if(maps.services&&maps.Map)resolve(maps);else fail()});
  };
  document.head.append(script);
 }).catch(error=>{pending=undefined;throw error});
}
export const mapHelp=key?'카카오 JavaScript 키의 SDK 도메인에 현재 주소 '+location.origin+'이 등록되어 있는지 확인하세요. 기본 실행 주소는 http://localhost:5173 입니다.':'프로젝트 .env.local의 VITE_KAKAO_MAP_KEY에 JavaScript 키를 설정하고 개발 서버를 재시작하세요.';
export async function searchPlaces(query){
 const maps=await loadMaps();
 const keyword=query.replace(/^(부산광역시|부산시|부산)\s+/,'').trim();
 return new Promise((resolve,reject)=>{
  new maps.services.Places().keywordSearch(keyword||query,(data,status)=>{
   if(status===maps.services.Status.OK)resolve(data.filter(p=>/^부산/.test(p.address_name)||/^부산/.test(p.road_address_name)));
   else if(status===maps.services.Status.ZERO_RESULT)resolve([]);
   else reject(new Error('카카오 장소 검색에 실패했습니다.'));
  },{location:new maps.LatLng(...center)});
 });
}
export default function KakaoMap({stops,lines=noLines}){
 const host=useRef(null);
 const [instance,setInstance]=useState(null);
 const [error,setError]=useState('');
 useEffect(()=>{
  let live=true, observer;
  loadMaps().then(maps=>{
   if(!live)return;
   const map=new maps.Map(host.current,{center:new maps.LatLng(...center),level:8});
   observer=new ResizeObserver(()=>{const point=map.getCenter();map.relayout();map.setCenter(point)});
   observer.observe(host.current);
   setInstance({maps,map});
  }).catch(e=>{if(live){console.warn('[Kakao 지도]',e.message,mapHelp);setError(e.message)}});
  return()=>{live=false;observer?.disconnect()};
 },[]);
 useEffect(()=>{
  if(!instance)return;
  const {maps,map}=instance;
  const info=new maps.InfoWindow({removable:true});
  const bounds=new maps.LatLngBounds();
  const paths=lines.map(line=>new maps.Polyline({map,path:line.map(([x,y])=>{const p=new maps.LatLng(y,x);bounds.extend(p);return p}),strokeWeight:5,strokeColor:'#168deb',strokeOpacity:.9}));
  const entries=stops.flatMap((stop,i)=>{
   if(!stop.place)return [];
   const point=new maps.LatLng(Number(stop.place.y),Number(stop.place.x));
   const color=i===0?'#009781':i===stops.length-1?'#df5b20':'#127be3';
   const svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 42"><path d="M16 40S1 23 1 16a15 15 0 0 1 30 0c0 7-15 24-15 24Z" fill="'+color+'" stroke="white" stroke-width="2"/><circle cx="16" cy="15" r="5" fill="white"/></svg>';
   const image=new maps.MarkerImage('data:image/svg+xml,'+encodeURIComponent(svg),new maps.Size(32,42),{offset:new maps.Point(16,40)});
   const marker=new maps.Marker({map,position:point,image,title:stop.place.place_name,clickable:true});
   const handle=()=>{
    const box=document.createElement('div');box.className='marker-info';
    const name=document.createElement('strong');name.textContent=stop.place.place_name;
    const address=document.createElement('div');address.textContent=stop.place.road_address_name||stop.place.address_name;
    box.append(name,address);info.setContent(box);info.open(map,marker);
   };
   maps.event.addListener(marker,'click',handle);bounds.extend(point);
   return [{marker,handle,point}];
  });
  if(entries.length===1){map.setLevel(5);map.panTo(entries[0].point)}
  else if(entries.length>1||paths.length)map.setBounds(bounds,65,65,100,65);
  return()=>{info.close();paths.forEach(p=>p.setMap(null));entries.forEach(({marker,handle})=>{maps.event.removeListener(marker,'click',handle);marker.setMap(null)})};
 },[instance,stops,lines]);
 return <section className="map-panel" aria-label="부산 지도"><div className="map-host" ref={host}/>
  {!instance&&<div className="map-placeholder" role="status"><span className="eyebrow">◈ 부산 지도</span><h2>{error||'카카오 지도 연결 중…'}</h2>{error&&<p>{mapHelp}</p>}</div>}
  {instance&&<div className="map-controls"><button type="button" aria-label="지도 확대" onClick={()=>instance.map.setLevel(instance.map.getLevel()-1)}>+</button><button type="button" aria-label="지도 축소" onClick={()=>instance.map.setLevel(instance.map.getLevel()+1)}>−</button><button type="button" aria-label="부산 중심으로 초기화" onClick={()=>{instance.map.setLevel(8);instance.map.setCenter(new instance.maps.LatLng(...center))}}>◎</button></div>}
  <aside className="legend marker-legend"><strong>ⓘ 지도 안내</strong><span><i className="green"/>출발지</span><span><i className="orange"/>도착지</span><span><i className="blue"/>경유지</span><small>{lines.length?'파란 선: 자체 탐색 경로 · 통행 허용 미확인':'선택한 장소를 표시합니다.'}</small></aside>
 </section>;
}
