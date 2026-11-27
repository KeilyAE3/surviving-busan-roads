"""National directed network and conservative turn records.

Reuses the validated topology and geodesic terminal-bearing method from the
former analyze.py/finalize_data.py, without their unrelated dataset imports.
"""
from collections import defaultdict, Counter
import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
from pyproj import Geod
from common import RAW, js, read_csv, status

TURN_CODES = {'001':'비보호회전','002':'버스만회전','003':'회전금지','011':'U-TURN',
              '012':'P-TURN','101':'좌회전금지','102':'직진금지','103':'우회전금지'}
TURN_CODE_SOURCE = 'national_node_link/reference/166343601.gif'

def build_network():
    base = RAW / 'national_node_link'
    source_links = read_csv(base / '도로링크.csv')
    source_nodes = read_csv(base / '노드.csv')
    turns = read_csv(base / '회전정보.csv')
    lmap = dict(링크ID='link_id', 시작노드ID='from_node_id', 종료노드ID='to_node_id',
                도로명='road_name', 도로등급코드='road_rank_code', 도로유형코드='road_type_code',
                도로사용코드='road_use_code', 통행제한차량코드='restriction_vehicle_code',
                통과제한하중='weight_limit_raw', 통과제한높이='height_limit_raw', 차로수='lane_count',
                구간길이='length_m', 도로좌표_WKT='geometry_wkt', 제한속도='speed_limit_kmh', 연결로코드='ramp_code')
    nmap = dict(노드ID='node_id', 노드명='node_name', 노드유형코드='node_type_code', 경도='lon', 위도='lat')
    links = source_links[list(lmap)].rename(columns=lmap)
    nodes = source_nodes[list(nmap)].rename(columns=nmap)
    assert len(links)==74967 and len(nodes)==52597
    assert links.link_id.is_unique and nodes.node_id.is_unique
    assert links.from_node_id.isin(nodes.node_id).all() and links.to_node_id.isin(nodes.node_id).all()
    for col in ['lane_count', 'length_m', 'speed_limit_kmh']:
        links[col] = pd.to_numeric(links[col], errors='raise')
        assert links[col].gt(0).all()
    for col in ['lon','lat']: nodes[col] = pd.to_numeric(nodes[col], errors='raise')
    links['road_in_use'] = links.road_use_code.eq('0')
    assert set(links.road_use_code)=={'0','1'}
    geo = gpd.read_file(base/'도로망_공간자료.gpkg', layer='road_links')
    ng = gpd.read_file(base/'도로망_공간자료.gpkg', layer='road_nodes')
    assert geo.crs.to_epsg()==4326 and ng.crs.to_epsg()==4326
    geo['LINK_ID'] = geo.LINK_ID.astype(str)
    geo = geo.set_index('LINK_ID').loc[links.link_id].reset_index()
    assert set(geo.LINK_ID)==set(links.link_id) and len(geo)==len(links)
    for a,b in [('from_node_id','F_NODE'),('to_node_id','T_NODE'),('lane_count','LANES'),('speed_limit_kmh','MAX_SPD')]:
        assert np.array_equal(links[a].astype(str).values,geo[b].astype(str).values), a
    wkt = shapely.from_wkt(links.geometry_wkt.values)
    # LAB CSV rounds coordinates to six decimals; GPKG retains full precision.
    csv_wkt_max_error_deg=float(shapely.hausdorff_distance(wkt,geo.geometry.values).max())
    assert shapely.equals_exact(wkt,geo.geometry.values,1e-6).all()
    links['geometry_wkt']=shapely.to_wkt(geo.geometry.values,rounding_precision=-1)
    assert geo.is_valid.all() and (~geo.is_empty).all()
    ng['NODE_ID'] = ng.NODE_ID.astype(str)
    ng = ng.set_index('NODE_ID').loc[nodes.node_id]
    assert len(ng)==len(nodes)
    assert np.allclose(ng.geometry.x,nodes.lon,atol=1e-10,rtol=0)
    assert np.allclose(ng.geometry.y,nodes.lat,atol=1e-10,rtol=0)
    geod = Geod(ellps='WGS84')
    xy = nodes.set_index('node_id')[['lon','lat']].to_dict('index')
    bearings = {}; endpoint_distances = []; ratios = []; direction_ok={}
    for r,g in zip(links.itertuples(index=False),geo.geometry):
        co = list(g.coords); f=xy[r.from_node_id]; t=xy[r.to_node_id]
        direct = geod.inv(*co[0][:2],f['lon'],f['lat'])[2] + geod.inv(*co[-1][:2],t['lon'],t['lat'])[2]
        reverse = geod.inv(*co[-1][:2],f['lon'],f['lat'])[2] + geod.inv(*co[0][:2],t['lon'],t['lat'])[2]
        ok = direct<=2 and direct<=reverse
        direction_ok[r.link_id]=ok; endpoint_distances.append(direct)
        start=next((p for p in co[1:] if p[:2]!=co[0][:2]),None)
        end=next((p for p in reversed(co[:-1]) if p[:2]!=co[-1][:2]),None)
        bearings[r.link_id] = ((geod.inv(*co[0][:2],*start[:2])[0]%360,
                               geod.inv(*end[:2],*co[-1][:2])[0]%360) if ok and start and end else (None,None))
        actual_length=geod.geometry_length(g)
        if actual_length>0: ratios.append(r.length_m/actual_length)
    inc=links.groupby('to_node_id').link_id.agg(list).to_dict()
    out=links.groupby('from_node_id').link_id.agg(list).to_dict()
    nodes['incoming_link_count']=nodes.node_id.map(lambda n:len(inc.get(n,[])))
    nodes['outgoing_link_count']=nodes.node_id.map(lambda n:len(out.get(n,[])))
    nodes['merge_topology_candidate']=nodes.incoming_link_count.ge(2)&nodes.outgoing_link_count.eq(1)
    nodes['diverge_topology_candidate']=nodes.incoming_link_count.eq(1)&nodes.outgoing_link_count.ge(2)
    nodes['intersection_type_candidate']=[f'directed_in_{a}_out_{b}' for a,b in zip(nodes.incoming_link_count,nodes.outgoing_link_count)]
    nodes['hd_intersection_details_json']='null';nodes['hd_merge_diverge_details_json']='null'
    fields={'lon':{'unit':'degree','crs':'EPSG:4326'},'lat':{'unit':'degree','crs':'EPSG:4326'},
            'incoming_link_count':{'status':'derived_including_unused_links','unit':'directed_links'},
            'outgoing_link_count':{'status':'derived_including_unused_links','unit':'directed_links'},
            'intersection_type_candidate':{'status':'topology_candidate_not_physical_junction'},
            'merge_topology_candidate':{'status':'topology_candidate'},'diverge_topology_candidate':{'status':'topology_candidate'},
            'hd_intersection_details_json':{'source':'hd_map','status':'unconfirmed'},
            'hd_merge_diverge_details_json':{'source':'hd_map','status':'unconfirmed'}}
    for f in fields.values():
        if f.get('source')=='hd_map':f.update(version='2019/2020/2024_model_2025_delivery',match='candidate_only')
    nodes['feature_status_json']=status('national_node_link','2026-09-14/LAB_v4','native_id',fields)
    lookup=links.set_index('link_id'); records=defaultdict(list); turn_quality=Counter()
    for r in turns.to_dict('records'):
        a,b,n=r['진입링크ID'],r['진출링크ID'],r['노드ID']
        if a not in lookup.index or b not in lookup.index: turn_quality['missing_link']+=1;continue
        if lookup.at[a,'to_node_id']!=n or lookup.at[b,'from_node_id']!=n:
            turn_quality['node_direction_mismatch']+=1;continue
        turn_quality['valid_topology']+=1
        records[n,a,b].append(dict(turn_id=r['회전ID'],type_code=r['회전유형코드'],operation_code=r['회전운영코드'],
                                  type_label=TURN_CODES.get(r['회전유형코드']),code_source=TURN_CODE_SOURCE))
    lane=lookup.lane_count.to_dict();use=lookup.road_in_use.to_dict(); transitions=[]
    for n in sorted(inc):
        for a in sorted(inc[n]):
            for b in sorted(out.get(n,[])):
                ev=records.get((n,a,b));bi=bearings[a][1];bo=bearings[b][0]
                permission='unknown'
                if ev:
                    if any(e['operation_code']!='0' for e in ev): permission='unknown_time_condition'
                    elif all(e['type_code'] in {'003','101','102','103'} for e in ev): permission='prohibited_recorded'
                    else: permission='unknown_recorded_maneuver'
                transitions.append(dict(node_id=n,in_link_id=a,out_link_id=b,lanes_in=lane[a],lanes_out=lane[b],
                    lane_delta=lane[b]-lane[a],lane_drop_boundary_candidate=lane[b]<lane[a],
                    approach_bearing_deg=bi,departure_bearing_deg=bo,turn_angle_deg=(bo-bi+180)%360-180 if bi is not None and bo is not None else None,
                    turn_permission_status=permission,turn_record_codes_json=js(ev),hd_transition_status='unconfirmed',
                    hd_transition_details_json='null',transition_in_use=bool(use[a] and use[b])))
    trans=pd.DataFrame(transitions)
    trans['feature_status_json']=status('national_node_link','2026-09-14/LAB_v4','topological_pair',{
        'lane_delta':{'status':'derived_out_minus_in','unit':'lanes'},'lane_drop_boundary_candidate':{'status':'boundary_candidate_not_lane_end'},
        'approach_bearing_deg':{'unit':'degree_clockwise_from_north','status':'terminal_geodesic'},
        'departure_bearing_deg':{'unit':'degree_clockwise_from_north','status':'terminal_geodesic'},
        'turn_angle_deg':{'unit':'degree_positive_right','status':'derived'},
        'turn_permission_status':{'status':'record_dependent_missing_is_unknown','code_source':TURN_CODE_SOURCE},
        'hd_transition_status':{'source':'hd_map','version':'2019/2020/2024_model_2025_delivery','match':'candidate_only','status':'unconfirmed'},
        'hd_transition_details_json':{'source':'hd_map','version':'2019/2020/2024_model_2025_delivery','match':'candidate_only','status':'unconfirmed'}})
    for c in ['lane_direction_details_json','lane_drop_details_json','lane_change_intervals_json','hd_source_refs']: links[c]='null'
    links['lane_change_candidate_length_m']=np.nan
    links['hd_match_status']='not_matched';links['hd_coverage_status']='not_assessed_outside_candidates'
    fields={'road_in_use':{'status':'derived_use_code_0'},'restriction_vehicle_code':{'status':'raw_code_uninterpreted'},
            'weight_limit_raw':{'unit':'kg','status':'raw_zero_sentinel_not_interpreted'},
            'height_limit_raw':{'unit':'cm','status':'raw_zero_sentinel_and_extremes_not_interpreted'},
            'lane_count':{'unit':'lanes','status':'source_excludes_auxiliary_lanes'},'length_m':{'unit':'m'},
            'geometry_wkt':{'unit':'degree','crs':'EPSG:4326','status':'full_precision_gpkg_csv_agrees_within_1e-6_degree'},'speed_limit_kmh':{'unit':'km/h'},
            'lane_direction_details_json':{'source':'hd_map','status':'raw_evidence_only_if_present'},
            'lane_drop_details_json':{'source':'hd_map','status':'unconfirmed_lane_end'},
            'lane_change_intervals_json':{'source':'hd_map','status':'codebook_unverified_or_RM1_absent'},
            'lane_change_candidate_length_m':{'source':'hd_map','unit':'m','status':'codebook_unverified_or_RM1_absent'}}
    for key in ['hd_match_status','hd_coverage_status','hd_source_refs']:
        fields[key]={'source':'hd_map','status':'candidate_evidence_or_not_matched'}
    for f in fields.values():
        if f.get('source')=='hd_map':f.update(version='2019/2020/2024_model_2025_delivery',match='candidate_only')
    links['feature_status_json']=status('national_node_link','2026-09-14/LAB_v4','native_id',fields)
    summary=dict(links=len(links),nodes=len(nodes),unused_links=int((~links.road_in_use).sum()),length_m=float(links.length_m.sum()),
                 transitions=len(trans),turn_validation=dict(turn_quality),turn_permissions=trans.turn_permission_status.value_counts().to_dict(),
                 lane_drop_boundary_candidates=int(trans.lane_drop_boundary_candidate.sum()),
                 direction_verified=sum(direction_ok.values()),endpoint_distance_sum_max_m=max(endpoint_distances),
                 stored_length_geodesic_ratio_quantiles=np.quantile(ratios,[0,.01,.5,.99,1]).tolist(),
                 height_above_1000cm=links.loc[pd.to_numeric(links.height_limit_raw).gt(1000),'link_id'].tolist(),
                 source_update_range=[source_links['갱신일'].min(),source_links['갱신일'].max()],
                 geometry_csv_gpkg_agree_within_1e_6_degree=True,csv_wkt_max_error_degree=csv_wkt_max_error_deg,source_connections_agree=False)
    conn=read_csv(base/'노드별연결.csv')
    expected={(l,n,'진입') for l,n in zip(links.link_id,links.to_node_id)}|{(l,n,'진출') for l,n in zip(links.link_id,links.from_node_id)}
    actual=set(conn[['링크ID','노드ID','진입진출구분']].itertuples(index=False,name=None))
    assert actual==expected and len(conn)==len(expected)
    summary['source_connections_agree']=True
    projected=gpd.GeoDataFrame(links[['link_id','road_name','road_type_code','from_node_id','to_node_id']].copy(),geometry=geo.geometry,crs=4326).to_crs(5179)
    return links,nodes,trans,projected,summary
