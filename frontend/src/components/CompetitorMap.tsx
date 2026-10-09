import {MapContainer,TileLayer,CircleMarker,Popup} from 'react-leaflet';
import type {LatLngTuple} from 'leaflet';
import type {Competitor} from '../types/analysis';
import 'leaflet/dist/leaflet.css';
import {MapResize} from './MapResize';
export function CompetitorMap({competitors}:{competitors:Competitor[]}){
 const points=competitors.filter(c=>c.latitude!==null&&c.longitude!==null);
 if(!points.length)return <p className="empty">No usable coordinates were returned. Available businesses are listed below.</p>;
 const bounds:LatLngTuple[]=points.map(c=>[c.latitude!,c.longitude!]);
 return <div className="map" aria-label={`Map of ${points.length} competitors. The paginated table below lists these locations.`}><MapContainer bounds={bounds} boundsOptions={{padding:[35,35],maxZoom:14}} scrollWheelZoom={false} style={{height:'100%',width:'100%'}}><MapResize/><TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"/>{points.map(c=><CircleMarker key={c.rank} center={[c.latitude!,c.longitude!]} radius={9} pathOptions={{color:'#fff',weight:2,fillColor:'#155eb5',fillOpacity:.9}}><Popup><strong>{c.name}</strong><br/>{c.address}<br/>{c.rating??'Unrated'} · {c.review_count} reviews</Popup></CircleMarker>)}</MapContainer></div>
}
