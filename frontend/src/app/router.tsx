import {createBrowserRouter,Link,NavLink,Outlet} from 'react-router-dom';
import {lazy,Suspense} from 'react';
import {RouteError} from './RouteError';
import {PrivateResearchPage} from '../pages/PrivateResearchPage';
const VentureHome=lazy(()=>import('../pages/VenturePages').then(m=>({default:m.VentureHome})));
const VentureReport=lazy(()=>import('../pages/VenturePages').then(m=>({default:m.VentureReport})));
const VentureReports=lazy(()=>import('../pages/VenturePages').then(m=>({default:m.VentureReports})));
const ResearchLandingPage=lazy(()=>import('../pages/ResearchLandingPage').then(m=>({default:m.ResearchLandingPage})));
import {CompareReportsPage} from '../pages/CompareReportsPage';
const ResearchScopeLayout=lazy(()=>import('../pages/ResearchScopePage').then(m=>({default:m.ResearchScopeLayout})));
const ResearchScopeHome=lazy(()=>import('../pages/ResearchScopePage').then(m=>({default:m.ResearchScopeHome})));
const ResearchScopeReport=lazy(()=>import('../pages/ResearchScopePage').then(m=>({default:m.ResearchScopeReport})));
function Layout(){return <div className="venture-shell"><a className="skip-link" href="#main">Skip to content</a><header className="site-header"><Link className="brand" to="/">VentureAtlas<span className="brand-sub">Evidence for your next venture</span></Link><nav aria-label="Main navigation"><NavLink to="/" end>New analysis</NavLink><NavLink to="/reports">Reports</NavLink><NavLink to="/compare">Compare</NavLink></nav></header><main id="main"><Suspense fallback={<p>Loading workspace…</p>}><Outlet/></Suspense></main><footer className="site-footer">VentureAtlas · Market research with SerpApi</footer></div>}
export const router=createBrowserRouter([{path:'/research-scope',errorElement:<RouteError/>,element:<Suspense fallback={<p>Loading research workspace…</p>}><ResearchScopeLayout/></Suspense>,children:[{index:true,element:<ResearchScopeHome/>},{path:'about',element:<ResearchLandingPage/>},{path:'private',element:<PrivateResearchPage/>},{path:'reports/:id',element:<ResearchScopeReport/>}]},{errorElement:<RouteError/>,element:<Layout/>,children:[{path:'/',element:<VentureHome/>},{path:'/market',element:<VentureHome/>},{path:'/reports',element:<VentureReports/>},{path:'/reports/:id',element:<VentureReport/>,children:[{path:'research',element:null},{path:'strategy',element:null}]},{path:'/compare',element:<CompareReportsPage/>},{path:'*',element:<p>Page not found. <Link to="/">Open VentureAtlas</Link> · <Link to="/research-scope">Open ResearchScope</Link></p>}]}]);
