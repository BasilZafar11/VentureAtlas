import {MapContainer,TileLayer,CircleMarker,Popup,Polygon,Polyline,useMapEvents} from 'react-leaflet';
import type {Competitor} from '../types/analysis';
import type {Point} from '../lib/exploration';
import 'leaflet/dist/leaflet.css';
import {MapResize} from './MapResize';
function Drawing({add,drawing}:{add:(p:Point)=>void;drawing:boolean}){useMapEvents({click:e=>{if(drawing)add([e.latlng.lat,e.latlng.lng])}});return <MapResize/>}
export default function ServiceAreaMap({places,vertices,areas,add,drawing}:{places:Competitor[];vertices:Point[];areas:{name:string;points:Point[]}[];add:(p:Point)=>void;drawing:boolean}){
 const bounds=places.map(p=>[p.latitude!,p.longitude!] as Point);
 return <div className="map" aria-label="Draw a service area by clicking map vertices. Coordinate entry is available below."><MapContainer bounds={bounds} boundsOptions={{padding:[30,30],maxZoom:13}} scrollWheelZoom={false} style={{height:'100%',width:'100%'}}><TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"/><Drawing add={add} drawing={drawing}/>{places.map(p=><CircleMarker key={p.rank} center={[p.latitude!,p.longitude!]} radius={6}><Popup>{p.name}</Popup></CircleMarker>)}{areas.map((a,i)=><Polygon key={i} positions={a.points} pathOptions={{color:['#007d78','#7352ad','#b06516','#155eb5'][i]}}><Popup>{a.name}</Popup></Polygon>)}{vertices.length>=3?<Polygon positions={vertices} pathOptions={{color:'#155eb5',dashArray:'5 5'}}/>:<Polyline positions={vertices}/>}</MapContainer></div>;
}
