import React, {useEffect,useState} from 'react';
import Home from './pages/Home.jsx';
import Route from './pages/Route.jsx';
import Result from './pages/Result.jsx';

const links=[['#/','홈'],['#/route','경로 분석'],['#/points','주의 포인트'],['#/about','서비스 소개']];
export default function App(){
  const [hash,setHash]=useState(location.hash||'#/');
  const [stops,setStops]=useState([{id:0,text:''},{id:1,text:''}]);
  const [option,setOption]=useState(0);
  useEffect(()=>{const sync=()=>setHash(location.hash||'#/');addEventListener('hashchange',sync);return()=>removeEventListener('hashchange',sync)},[]);
  useEffect(()=>{
    if(hash==='#/about'||hash==='#/points') document.getElementById(hash.slice(2))?.scrollIntoView();
    else window.scrollTo(0,0);
  },[hash]);
  const active=hash==='#/result'?'#/route':hash;
  return <><header className="top"><div className="shell nav"><a className="brand" href="#/"><img src={import.meta.env.BASE_URL+'img/logo.svg'} alt=""/>부산에서 운전자로 살아남기</a><nav aria-label="주 메뉴">{links.map(([url,label])=><a key={url} href={url} aria-current={active===url?'page':undefined}>{label}</a>)}</nav></div></header>
  {hash==='#/route'?<Route {...{stops,setStops,option,setOption}}/>:hash==='#/result'?<Result/>:<Home/>}</>;
}
