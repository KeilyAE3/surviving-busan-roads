"""Read saved deliverables and fail on integrity or semantic-contract errors."""
import itertools
import json
import numpy as np
import pandas as pd
import shapely
from common import read_csv, sha, verify_sources
from traffic import PERIODS, TRAFFIC_COLS, VALUE_COLS

TABLES=['road_nodes','road_links','road_transitions','road_traffic','view_t_groups','hd_lane_link_matches']

def validate(output,expected_sources=None):
    frames={};report={'checks':{},'tables':{}}
    for name in TABLES:
        p=output/(name+'.csv')
        with p.open('rb') as f:assert f.read(3)==b'\xef\xbb\xbf',f'BOM missing: {name}'
        d=read_csv(p);frames[name]=d
        assert not d.columns.duplicated().any()
        for col in [c for c in d if c.endswith('_json') or c=='hd_source_refs']:
            for value in d[col].unique():
                assert value!='',f'JSON must use literal null: {name}.{col}'
                json.loads(value,parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)))
        report['tables'][name]=dict(rows=len(d),columns=len(d.columns),column_names=list(d),sha256=sha(p),bytes=p.stat().st_size)
    n,l,t,r,g,h=[frames[x] for x in TABLES]
    assert len(n)==52597 and len(l)==74967 and len(t)==114619
    for d,key in [(n,['node_id']),(l,['link_id']),(t,['node_id','in_link_id','out_link_id']),
                  (r,['link_id','source','source_group_id','reference_year','day_type','period','observed_at']),
                  (g,['source_group_id','reference_year','day_type','period']),(h,['match_id'])]:
        assert not d.duplicated(key).any(),f'Duplicate key {key}'
        assert d[key[0]].ne('').all()
    for col in ['from_node_id','to_node_id']:assert l[col].isin(n.node_id).all()
    for col in ['in_link_id','out_link_id']:assert t[col].isin(l.link_id).all()
    assert t.node_id.isin(n.node_id).all() and r.link_id.isin(l.link_id).all()
    assert h.loc[h.link_id.ne(''),'link_id'].isin(l.link_id).all()
    assert set(l.link_id)==set(read_csv(__import__('common').RAW/'national_node_link/도로링크.csv')['링크ID'])
    assert set(n.node_id)==set(read_csv(__import__('common').RAW/'national_node_link/노드.csv')['노드ID'])
    lookup=l.set_index('link_id')
    assert t.in_link_id.map(lookup.to_node_id).equals(t.node_id)
    assert t.out_link_id.map(lookup.from_node_id).equals(t.node_id)
    assert pd.to_numeric(t.lane_delta).equals(pd.to_numeric(t.lanes_out)-pd.to_numeric(t.lanes_in))
    assert (t.lane_drop_boundary_candidate.eq('True')==pd.to_numeric(t.lane_delta).lt(0)).all()
    assert (l.road_in_use.eq('True')==l.road_use_code.eq('0')).all()
    assert l.road_in_use.eq('False').sum()==418
    assert (t.transition_in_use.eq('True')==(t.in_link_id.map(lookup.road_in_use).eq('True')&t.out_link_id.map(lookup.road_in_use).eq('True'))).all()
    ic=l.groupby('to_node_id').size();oc=l.groupby('from_node_id').size()
    assert np.array_equal(pd.to_numeric(n.incoming_link_count),n.node_id.map(ic).fillna(0))
    assert np.array_equal(pd.to_numeric(n.outgoing_link_count),n.node_id.map(oc).fillna(0))
    assert len(t)==sum(ic.get(k,0)*oc.get(k,0) for k in set(ic.index)|set(oc.index))
    geom=shapely.from_wkt(l.geometry_wkt.values)
    assert shapely.is_valid(geom).all() and (~shapely.is_empty(geom)).all()
    b=shapely.bounds(geom)
    assert (b[:,0]>=120).all() and (b[:,2]<=135).all() and (b[:,1]>=30).all() and (b[:,3]<=40).all()
    for col in ['lane_count','length_m','speed_limit_kmh']:assert pd.to_numeric(l[col]).gt(0).all()
    angle=pd.to_numeric(t.turn_angle_deg.replace('',np.nan));assert angle.dropna().between(-180,180).all()
    bi=pd.to_numeric(t.approach_bearing_deg.replace('',np.nan));bo=pd.to_numeric(t.departure_bearing_deg.replace('',np.nan))
    assert np.allclose(angle, (bo-bi+180)%360-180,equal_nan=True)
    assert set(r.columns)==set(TRAFFIC_COLS)
    vt=r[r.source.eq('view_t')];api=r[r.source.eq('busan_link_traffic')]
    assert set(vt.period)==set(PERIODS+['weekday_all']) and vt.reference_year.eq('2025').all()
    assert vt.day_type.eq('weekday').all() and vt.observed_at.eq('').all()
    assert api.period.eq('snapshot').all() and api.observed_at.eq('2026-11-25T15:00:00+09:00').all()
    assert api.reference_year.eq('').all() and api.day_type.eq('').all()
    assert r.density_proxy_veh_per_km.eq('').all() and r.volume_per_hour.eq('').all()
    assert api.observed_speed_kmh.eq('').all()
    assert vt.observed_speed_raw.eq('').all()
    period_rows=vt.period.ne('weekday_all')
    assert vt.loc[period_rows,['congestion_frequency','congestion_time']].eq('').all().all()
    assert vt.loc[~period_rows,['estimated_volume_total_raw','mean_speed_kmh']].eq('').all().all()
    assert vt.loc[vt.match_status.str.startswith('ambiguous'),VALUE_COLS].eq('').all().all()
    assert l.lane_change_candidate_length_m.eq('').all() and l.lane_change_intervals_json.eq('null').all()
    assert not l.hd_match_status.eq('confirmed').any()
    for col in ['congestion_frequency','congestion_time']:
        assert pd.to_numeric(g[col].replace('',np.nan)).dropna().between(0,100).all()
    for col in VALUE_COLS+['observed_speed_raw']:
        assert pd.to_numeric(r[col].replace('',np.nan)).dropna().ge(0).all()
    group_index=g.set_index(['source_group_id','reference_year','day_type','period'])
    expected_pairs=set()
    for rec in g.to_dict('records'):
        for lid in json.loads(rec['its_link_ids_json']):
            if lid in lookup.index:expected_pairs.add((lid,rec['source_group_id'],rec['period']))
    actual_pairs=set(vt[['link_id','source_group_id','period']].itertuples(index=False,name=None))
    assert expected_pairs==actual_pairs
    for rec in vt.to_dict('records'):
        group=group_index.loc[(rec['source_group_id'],rec['reference_year'],rec['day_type'],rec['period'])]
        assert rec['link_id'] in json.loads(group['its_link_ids_json'])
        if rec['match_status']=='exact_its_reference':
            for col in VALUE_COLS:assert rec[col]==group[col]
    # All competing group references must be flagged; never silently choose one.
    counts=vt.groupby(['link_id','period']).source_group_id.nunique()
    for rec in vt[['link_id','period','match_status']].itertuples(index=False):
        assert (counts[rec.link_id,rec.period]>1)==(rec.match_status=='ambiguous_multiple_groups')
    match_ids=set(h.match_id)
    for val in l.hd_source_refs[l.hd_source_refs.ne('null')]:assert set(json.loads(val))<=match_ids
    for rec in h.loc[h.interval_start_m.ne('')].itertuples(index=False):
        assert float(rec.interval_start_m)>=0 and float(rec.interval_end_m)>=float(rec.interval_start_m)
        # National stored lengths differ slightly by projection; permit 0.2% + 1 m.
        assert float(rec.interval_end_m)<=float(lookup.at[rec.link_id,'length_m'])*1.002+1
    for rec in t.loc[t.turn_permission_status.eq('prohibited_recorded')].itertuples(index=False):
        ev=json.loads(rec.turn_record_codes_json)
        assert ev and all(x['type_code'] in {'003','101','102','103'} and x['operation_code']=='0' for x in ev)
    final_sources=verify_sources()
    if expected_sources is not None:assert expected_sources==final_sources,'Source bytes changed during build'
    report['checks']={k:'passed' for k in ['utf8_bom','row_counts','primary_keys_null_safe','foreign_keys','full_base_network_preserved',
        'transition_direction_and_cartesian_count','lane_delta','unused_flags','node_degrees','valid_geometry_epsg4326',
        'angle_sign_and_range','traffic_period_and_observation_separation','view_t_group_relation_completeness',
        'view_t_ambiguity_withheld','traffic_group_values_equal','source_hashes','no_unverified_density_or_lane_change_distance',
        'json_valid_no_nan','hd_reference_integrity','turn_code_interpretation']}
    full=set(l.link_id);active=set(l.loc[l.road_in_use.eq('True'),'link_id']);length=pd.to_numeric(lookup.length_m).to_dict()
    def coverage(ids):
        ids=set(ids)&full;out={}
        for label,denom in [('all',full),('in_use',active)]:
            selected=ids&denom;total=sum(length[i] for i in sorted(denom));selected_len=sum(length[i] for i in sorted(selected))
            out[label]=dict(links=len(selected),link_pct=100*len(selected)/len(denom),length_m=selected_len,length_pct=100*selected_len/total)
        return out
    sets={'national_network':full,'view_t_reference':set(vt.link_id),'view_t_unambiguous':set(vt.loc[vt.match_status.eq('exact_its_reference'),'link_id']),
          'view_t_volume':set(vt.loc[vt.estimated_volume_total_raw.ne(''),'link_id']),
          'view_t_speed':set(vt.loc[vt.mean_speed_kmh.ne(''),'link_id']),
          'view_t_congestion':set(vt.loc[vt.congestion_frequency.ne('')|vt.congestion_time.ne(''),'link_id']),
          'view_t_conflict':set(vt.loc[vt.match_status.str.startswith('ambiguous'),'link_id']),
          'api_reference_raw_speed':set(api.loc[api.observed_speed_raw.ne(''),'link_id']),
          'api_speed_kmh':set(), 'hd_geometry_candidate':set(h.loc[h.match_status.eq('candidate_geometry_supported'),'link_id']),
          'hd_any_candidate_or_rejected':set(h.loc[h.link_id.ne(''),'link_id']), 'hd_confirmed':set(),
          'lane_count':full,'length_geometry':full,'lane_change_candidate_length':set(),'density_proxy':set(),
          'lane_drop_boundary_incoming':set(t.loc[t.lane_drop_boundary_candidate.eq('True'),'in_link_id']),
          'turn_valid_record_incoming':set(t.loc[t.turn_record_codes_json.ne('null'),'in_link_id']),
          'turn_prohibited_incoming':set(t.loc[t.turn_permission_status.eq('prohibited_recorded'),'in_link_id']),
          'hd_transition_incoming':set(t.loc[t.hd_transition_status.eq('candidate_connectivity'),'in_link_id'])}
    for col in ['merge_topology_candidate','diverge_topology_candidate']:
        nn=set(n.loc[n[col].eq('True'),'node_id']);sets[col]=set(l.loc[l.from_node_id.isin(nn)|l.to_node_id.isin(nn),'link_id'])
    report['coverage']={k:coverage(v) for k,v in sets.items()}
    report['coverage_by_period']={p:{c:coverage(vt.loc[vt.period.eq(p)&vt[c].ne(''),'link_id'])
        for c in ['estimated_volume_total_raw','mean_speed_kmh','congestion_frequency','congestion_time']} for p in PERIODS+['weekday_all']}
    speed_sets=[set(vt.loc[vt.period.eq(p)&vt.mean_speed_kmh.ne(''),'link_id']) for p in PERIODS]
    report['coverage']['view_t_speed_all_three_periods']=coverage(set.intersection(*speed_sets))
    compare=['view_t_reference','view_t_volume','view_t_speed','view_t_congestion','api_reference_raw_speed','hd_geometry_candidate']
    report['intersections']={a+' & '+b:coverage(sets[a]&sets[b]) for a,b in itertools.combinations(compare,2)}
    report['intersections']['view_t_reference & api & hd_candidate']=coverage(sets['view_t_reference']&sets['api_reference_raw_speed']&sets['hd_geometry_candidate'])
    report['missing_and_zero']={name:{c:dict(null=int(d[c].eq('').sum()),zero=int(d[c].isin(['0','0.0']).sum()))
        for c in d if c not in {'geometry_wkt'} and not c.endswith('_json') and c!='hd_source_refs'} for name,d in frames.items()}
    report['source_hashes']=final_sources
    return report
