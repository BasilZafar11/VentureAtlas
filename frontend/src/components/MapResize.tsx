import {useEffect} from 'react';
import {useMap} from 'react-leaflet';
export function MapResize(){
 const map=useMap();
 useEffect(()=>{
  const element=map.getContainer();
  const observer=new ResizeObserver(()=>{if(element.clientWidth&&element.clientHeight)map.invalidateSize({pan:false})});
  observer.observe(element);
  return ()=>observer.disconnect();
 },[map]);
 return null;
}
