import React, {lazy,Suspense,useEffect,useState} from 'react';
import Home from './pages/Home.jsx';
import Route from './pages/Route.jsx';
import Result from './pages/Result.jsx';
import { api } from './data/evaluation.js';

const links=[['#/','홈'],['#/route','경로 분석'],['#/points','주의 포인트'],['#/about','서비스 소개']];
const DevInput=import.meta.env.DEV && import.meta.env.VITE_ENABLE_DEV_TOOLS==='true'
  ? lazy(()=>import('./ValidationInput.jsx')) : null;
export default function App(){
  const [hash,setHash]=useState(location.hash||'#/');
  const [stops,setStops]=useState([{id:0,text:''},{id:1,text:''}]);
  const [option,setOption]=useState(0);
  const [analysis,setAnalysis]=useState(null);
  const [analysisRequest,setAnalysisRequest]=useState(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  async function onAnalyze(request){
    if(busy)return;
    setBusy(true);setError('');setAnalysis(null);
    try{
      const result=await api('/api/evaluate',request);
      setAnalysis(result);setAnalysisRequest(request);location.hash='#/result';
    }catch(e){setError(e.message)}finally{setBusy(false)}
  }
  async function onRoute(settings){
    if(busy)return;
    setBusy(true);setError('');setAnalysis(null);
    try{
      const result=await api('/api/route',{...settings,places:stops.map(s=>({name:s.place.place_name,lon:Number(s.place.x),lat:Number(s.place.y)}))});
      setAnalysis(result);setAnalysisRequest(result.routing.evaluation_request);location.hash='#/result';
    }catch(e){setError(e.message)}finally{setBusy(false)}
  }
  useEffect(()=>{const sync=()=>setHash(location.hash||'#/');addEventListener('hashchange',sync);return()=>removeEventListener('hashchange',sync)},[]);
  useEffect(()=>{
    if(hash==='#/about'||hash==='#/points') document.getElementById(hash.slice(2))?.scrollIntoView();
    else window.scrollTo(0,0);
  },[hash]);
  const active=hash==='#/result'?'#/route':hash;
  const devPanel=DevInput?<Suspense fallback={<p>개발 도구 준비 중…</p>}><DevInput {...{onAnalyze,busy,error}}/></Suspense>:null;
  return <><header className="top"><div className="shell nav"><a className="brand" href="#/"><img src={import.meta.env.BASE_URL+'img/logo.svg'} alt=""/>부산에서 운전자로 살아남기</a><nav aria-label="주 메뉴">{links.map(([url,label])=><a key={url} href={url} aria-current={active===url?'page':undefined}>{label}</a>)}</nav></div></header>
  {hash==='#/route'?<Route {...{stops,setStops,option,setOption,devPanel,onRoute,busy,error}}/>:hash==='#/result'?<Result {...{analysis,analysisRequest,devPanel}}/>:<Home/>}</>;
}
