"""Model-specific HD evidence and conservative planar matching.

No candidate is promoted to a confirmed road correspondence: the base network
has no comparable elevation, and the version-specific HD codebooks were not
supplied/verified. Raw codes remain available for a later reviewed promotion.
"""
from collections import defaultdict, Counter
import hashlib
import json
import math
import struct
import warnings
import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
from shapely.geometry import Point, GeometryCollection
from shapely.strtree import STRtree
from common import RAW, ROOT, js, clean

LAYERS=['a1_node','a2_link','b2_surfacelinemark','b3_surfacemark','nt1_node','nt2_link','rm2_roadmarking']
LANE_FIELDS=['fromnodeid','tonodeid','l_linkid','r_linkid','laneno','direction','turn','linktype',
             'itslinkid','roadrank','roadtype','roadno','roadname','maxspeed','length','version','updatedate','surveydate']

def s(v):
    v=clean(v)
    return None if v is None or str(v).strip()=='' else (str(int(v)) if isinstance(v,float) and v.is_integer() else str(v))

def load_objects():
    layers=defaultdict(list);audit=[];identities=defaultdict(list);exact_duplicates=0
    for path in sorted((RAW/'hd_map').rglob('*.shp')):
        layer=next(k for k in LAYERS if path.stem.endswith('_'+k))
        for ext in ['.dbf','.shx','.prj','.cpg']: assert path.with_suffix(ext).exists()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            g=gpd.read_file(path)
        with path.with_suffix('.dbf').open('rb') as f: dbf_rows=struct.unpack('<I',f.read(8)[4:8])[0]
        shx_rows=(path.with_suffix('.shx').stat().st_size-100)//8
        assert dbf_rows==shx_rows==len(g),f'SHP/SHX/DBF row mismatch: {path.name}'
        with path.open('rb') as f: shp_declared_bytes=struct.unpack('>i',f.read(28)[24:28])[0]*2
        assert shp_declared_bytes==path.stat().st_size
        assert g.crs is not None
        crs=str(g.crs)
        if g.crs.to_epsg()!=5179:g=g.to_crs(5179)
        columns=list(g.columns);invalid=int((~g.geometry.is_valid).sum())
        audit.append(dict(path=path.relative_to(ROOT).as_posix(),layer=layer,rows=len(g),crs=crs,columns=columns,
                          invalid_xy=invalid,null_geometry=int(g.geometry.isna().sum()),empty=int(g.geometry.is_empty.sum()),versions=sorted({s(v) for v in g['version'] if s(v)}),
                          dbf_rows=dbf_rows,shx_rows=shx_rows,reader_warnings=sorted({str(w.message) for w in caught})))
        for rownum,r in enumerate(g.to_dict('records'),1):
            geom=r.pop('geometry');attrs={k:s(v) for k,v in r.items()}
            ref=dict(file=path.relative_to(ROOT).as_posix(),dbf_row=rownum)
            native_id=attrs['id'];assert native_id
            shape=shapely.force_2d(geom) if geom is not None else GeometryCollection()
            fp=hashlib.sha256((js({k:v for k,v in attrs.items() if k not in {'gid','rd_id'}})+(geom.wkb_hex if geom is not None else 'NULL')).encode()).hexdigest()
            key=(layer,native_id)
            same=next((o for o in identities[key] if o['fingerprint']==fp),None)
            if same:
                same['source_refs'].append(ref);exact_duplicates+=1;continue
            obj=dict(layer=layer,id=native_id,attrs=attrs,geometry=shape,source_refs=[ref],fingerprint=fp,
                     key=path.parent.name+'/'+layer+'/'+native_id)
            identities[key].append(obj);layers[layer].append(obj)
    conflicts=[]
    for key,items in identities.items():
        for o in items:o['conflict']=len(items)>1
        if len(items)>1:conflicts.append(dict(layer=key[0],id=key[1],variants=len(items)))
    assert len(audit)==51 and not list((RAW/'hd_map').rglob('*rm1*.shp'))
    return layers,dict(layers=audit,exact_object_duplicates_removed=exact_duplicates,object_conflicts=conflicts,
                       unique_objects_by_layer={k:len(v) for k,v in layers.items()},RM1_present=False)

def tangent(line,position):
    delta=min(2.0,line.length/4)
    a=line.interpolate(max(0,position-delta));b=line.interpolate(min(line.length,position+delta))
    if a.distance(b)<.01:return None
    return math.degrees(math.atan2(b.x-a.x,b.y-a.y))%360

def evaluate(lane,road):
    if lane.is_empty or road.is_empty or not lane.is_valid or lane.geom_type!='LineString':return None
    clipped=lane.intersection(road.buffer(20))
    pieces=[clipped] if clipped.geom_type=='LineString' else [g for g in getattr(clipped,'geoms',[]) if g.geom_type=='LineString']
    if not pieces:return None
    part=max(pieces,key=lambda g:g.length)
    if part.length<2:return None
    # Intersection may reverse line orientation. Recover the source path order.
    if lane.project(Point(part.coords[-1]))<lane.project(Point(part.coords[0])):part=shapely.reverse(part)
    pts=[part.interpolate(t,normalized=True) for t in [0,.25,.5,.75,1]]
    offsets=[road.project(p) for p in pts];distances=[p.distance(road) for p in pts]
    p=pts[2];a=tangent(lane,lane.project(p));b=tangent(road,road.project(p))
    angle=abs((a-b+180)%360-180) if a is not None and b is not None else 180
    road_overlap=road.intersection(lane.buffer(15)).length/road.length
    lane_overlap=lane.intersection(road.buffer(15)).length/lane.length
    monotonic=all(y-x>=-1 for x,y in zip(offsets,offsets[1:]))
    good=(angle<=25 and np.median(distances)<=12 and max(distances)<=20.001 and monotonic
          and offsets[-1]-offsets[0]>=2 and (road_overlap>=.6 or lane_overlap>=.8))
    return dict(start_m=round(min(offsets),3),end_m=round(max(offsets),3),
                median_distance_m=round(float(np.median(distances)),3),max_sample_distance_m=round(max(distances),3),
                direction_difference_deg=round(angle,3),road_overlap_fraction=round(road_overlap,6),
                lane_overlap_fraction=round(lane_overlap,6),projection_monotonic=monotonic,geometry_supported=good)

def build_hd(links,nodes,trans,projected):
    layers,info=load_objects()
    lanes=layers['a2_link']+layers['nt2_link'];hdnodes=layers['a1_node']+layers['nt1_node']
    lane_by_id=defaultdict(list);node_by_id=defaultdict(list)
    for o in lanes:lane_by_id[o['id']].append(o)
    for o in hdnodes:node_by_id[o['id']].append(o)
    incoming=defaultdict(list);outgoing=defaultdict(list)
    for o in lanes:
        incoming[o['attrs']['tonodeid']].append(o['id']);outgoing[o['attrs']['fromnodeid']].append(o['id'])
    marks=defaultdict(list);boundaries=defaultdict(list);mark_stats=Counter()
    for o in layers['b3_surfacemark']:
        if o['geometry'].is_empty or not o['geometry'].is_valid:
            mark_stats['B3_invalid_or_empty_geometry']+=1;continue
        target=o['attrs']['linkid'];candidates=lane_by_id.get(target,[])
        if len(candidates)!=1:mark_stats['B3_missing_or_ambiguous_link']+=1;continue
        lane=candidates[0];distance=o['geometry'].distance(lane['geometry'])
        if distance>5:mark_stats['B3_id_geometry_mismatch']+=1;continue
        marks[target].append(dict(mark_id=o['id'],type_code=o['attrs']['type'],kind_code=o['attrs']['kind'],
                                 distance_m=round(distance,3),match='id_and_planar_distance_candidate',
                                 interpretation='codebook_unverified',object_conflict=o['conflict'],source_refs=o['source_refs']))
        mark_stats['B3_id_and_distance_candidate']+=1
    for o in layers['b2_surfacelinemark']:
        for side in ['l_linkid','r_linkid']:
            lid=o['attrs'][side]
            if lid and len(lane_by_id.get(lid,[]))==1:
                boundaries[lid].append(dict(boundary_id=o['id'],type_code=o['attrs']['type'],kind_code=o['attrs']['kind'],
                                           side_field=side,other_lane_id=o['attrs']['r_linkid' if side=='l_linkid' else 'l_linkid'],
                                           object_conflict=o['conflict'],source_refs=o['source_refs']))
    # RM2 has no link ID. Diagnose spatial ambiguity but do not assign direction
    # or lane semantics without a verified orientation/code definition.
    newlanes=layers['nt2_link'];newtree=STRtree([o['geometry'] for o in newlanes])
    for o in layers['rm2_roadmarking']:
        if o['geometry'].is_empty or not o['geometry'].is_valid:
            mark_stats['RM2_invalid_or_empty_geometry']+=1;continue
        hits=newtree.query(o['geometry'],predicate='dwithin',distance=3)
        mark_stats['RM2_'+('no_nearby_lane' if len(hits)==0 else 'unique_spatial_only' if len(hits)==1 else 'multiple_spatial_candidates')]+=1
    geoms=projected.geometry.tolist();tree=STRtree(geoms);ids=projected.link_id.tolist();ix={k:i for i,k in enumerate(ids)}
    rows=[];supported=defaultdict(list);node_evidence=defaultdict(dict);ref_quality=Counter()
    national_nodes=gpd.GeoSeries(gpd.points_from_xy(nodes.lon,nodes.lat),crs=4326).to_crs(5179)
    national_node_geom=dict(zip(nodes.node_id,national_nodes))
    lane_matches=defaultdict(list)
    for pos,o in enumerate(lanes):
        attrs=o['attrs'];geom=o['geometry'];nid_from=attrs['fromnodeid'];nid_to=attrs['tonodeid']
        refs_ok=len(node_by_id.get(nid_from,[]))==1 and len(node_by_id.get(nid_to,[]))==1
        endpoint_ok=False
        if refs_ok and geom.geom_type=='LineString' and not geom.is_empty:
            fd=Point(geom.coords[0]).distance(node_by_id[nid_from][0]['geometry'])
            td=Point(geom.coords[-1]).distance(node_by_id[nid_to][0]['geometry'])
            endpoint_ok=fd<=.5 and td<=.5
        else:fd=td=None
        ref_quality['node_references_valid' if refs_ok else 'node_reference_missing_or_ambiguous']+=1
        ref_quality['endpoints_within_0_5m' if endpoint_ok else 'endpoints_unverified']+=1
        neighbours={k:('not_recorded' if not attrs[k] else 'present' if len(lane_by_id.get(attrs[k],[]))==1 else 'missing_or_ambiguous') for k in ['l_linkid','r_linkid']}
        id_candidate=attrs.get('itslinkid')
        candidate_ix=set(tree.query(geom,predicate='dwithin',distance=20).tolist()) if not geom.is_empty and geom.is_valid else set()
        if id_candidate in ix:candidate_ix.add(ix[id_candidate])
        evidence=[]
        for i in sorted(candidate_ix,key=lambda i:ids[i]):
            metric=evaluate(geom,geoms[i]);id_hit=ids[i]==id_candidate
            if metric is None or (not metric['geometry_supported'] and not id_hit):continue
            quality='candidate_geometry_supported' if metric['geometry_supported'] else 'id_geometry_rejected'
            if o['conflict']:quality='ambiguous_source_object'
            elif metric['geometry_supported'] and not endpoint_ok:quality='candidate_endpoint_unverified'
            evidence.append((i,metric,id_hit,quality))
        if not evidence:evidence=[(None,None,False,'unmatched_invalid_geometry' if geom.is_empty or not geom.is_valid else 'unmatched')]
        for i,metric,id_hit,quality in evidence:
            link=ids[i] if i is not None else None
            mid=hashlib.sha256((o['key']+'|'+str(link)).encode()).hexdigest()[:24]
            row=dict(match_id=mid,link_id=link,hd_lane_id=o['id'],hd_model=attrs['version'],hd_layer=o['layer'],
                     source_refs_json=js(o['source_refs']),lane_attributes_json=js({k:attrs.get(k) for k in LANE_FIELDS}),
                     match_method='its_id_plus_geometry' if id_hit else 'spatial_direction_overlap',match_status=quality,
                     interval_start_m=metric['start_m'] if metric else None,interval_end_m=metric['end_m'] if metric else None,
                     metrics_json=js(metric),topology_json=js(dict(node_refs_valid=refs_ok,endpoint_verified=endpoint_ok,
                         from_distance_m=fd,to_distance_m=td,neighbours=neighbours,
                         incoming_to_end=len(incoming[nid_to]),outgoing_from_end=len(outgoing[nid_to]))),
                     marking_evidence_json=js(marks.get(o['id']) if o['layer']=='a2_link' else None),
                     boundary_evidence_json=js(boundaries.get(o['id']) if o['layer']=='a2_link' else None),
                     review_reasons_json=js(['vertical_separation_unverified','source_version_alignment_unverified',
                                            'HD_model_codebook_unverified']+(['parallel_or_successive_road_candidates'] if len(evidence)>1 else [])))
            rows.append(row)
            if link and quality=='candidate_geometry_supported':
                supported[link].append((o,row));lane_matches[o['id']].append((link,mid))
                road=projected.iloc[i]
                for hdid,nid in [(nid_from,road.from_node_id),(nid_to,road.to_node_id)]:
                    if len(node_by_id.get(hdid,[]))==1:
                        hn=node_by_id[hdid][0];dist=hn['geometry'].distance(national_node_geom[nid])
                        if dist<=15:
                            node_evidence[nid][hdid]=dict(hd_node_id=hdid,raw_codes={k:v for k,v in hn['attrs'].items() if k in ['nodetype','nodetype1','nodetype2','nodetype3','startend1','startend2','startend3','groupid','version']},
                                incoming_lane_paths=len(incoming[hdid]),outgoing_lane_paths=len(outgoing[hdid]),distance_m=round(dist,3),
                                status='candidate_geometry_and_connectivity_not_physical_junction',source_refs=hn['source_refs'])
        if (pos+1)%3000==0:print(f'HD paths processed: {pos+1}/{len(lanes)}',flush=True)
    relations=pd.DataFrame(rows)
    link_index=links.set_index('link_id').index
    for lid,items in supported.items():
        idx=link_index.get_loc(lid)
        links.at[idx,'hd_match_status']='candidate_only'
        links.at[idx,'hd_coverage_status']='geometry_supported_not_confirmed'
        links.at[idx,'hd_source_refs']=js(sorted({r['match_id'] for o,r in items}))
        # The relation owns full raw evidence; avoid copying it to every road row.
        links.at[idx,'lane_direction_details_json']=js([dict(hd_lane_id=o['id'],match_id=r['match_id'],
            model=o['attrs']['version'],laneno=o['attrs'].get('laneno'),direction_code=o['attrs'].get('direction'),
            turn_code=o['attrs'].get('turn'),from_node_id=o['attrs']['fromnodeid'],to_node_id=o['attrs']['tonodeid'],
            interval_start_m=r['interval_start_m'],interval_end_m=r['interval_end_m'],status='raw_codes_uninterpreted_candidate') for o,r in items])
    # Keep rejected and endpoint-unverified references discoverable too.
    for lid,frame in relations.loc[relations.link_id.notna()].groupby('link_id'):
        idx=link_index.get_loc(lid)
        links.at[idx,'hd_source_refs']=js(sorted(frame.match_id.tolist()))
        if lid not in supported:
            links.at[idx,'hd_match_status']='unresolved_candidates'
            links.at[idx,'hd_coverage_status']='no_verified_correspondence'
    for idx,n in enumerate(nodes.node_id):
        if n in node_evidence:
            vals=[v for k,v in sorted(node_evidence[n].items())]
            nodes.at[idx,'hd_intersection_details_json']=js(vals)
            candidates=[v for v in vals if (v['incoming_lane_paths']>=2 and v['outgoing_lane_paths']==1) or (v['incoming_lane_paths']==1 and v['outgoing_lane_paths']>=2)]
            if candidates:nodes.at[idx,'hd_merge_diverge_details_json']=js(candidates)
    by_transition=defaultdict(list);road_lookup=links.set_index('link_id')
    for hdid,ins in incoming.items():
        for a in ins:
            for b in outgoing.get(hdid,[]):
                for la,ma in lane_matches.get(a,[]):
                    for lb,mb in lane_matches.get(b,[]):
                        n=road_lookup.at[la,'to_node_id']
                        if road_lookup.at[lb,'from_node_id']==n and hdid in node_evidence.get(n,{}):
                            by_transition[n,la,lb].append(dict(hd_node_id=hdid,in_hd_lane_id=a,out_hd_lane_id=b,
                                in_match_id=ma,out_match_id=mb,status='physical_path_candidate_legal_permission_unknown'))
    for idx,r in enumerate(trans[['node_id','in_link_id','out_link_id']].itertuples(index=False,name=None)):
        if r in by_transition:
            trans.at[idx,'hd_transition_status']='candidate_connectivity'
            trans.at[idx,'hd_transition_details_json']=js(by_transition[r])
    info.update(match_status_counts=relations.match_status.value_counts().to_dict(),relation_rows=len(relations),
                geometry_supported_links=len(supported),confirmed_links=0,raw_marking_diagnostics=dict(mark_stats),
                lane_topology=dict(ref_quality),node_candidate_count=len(node_evidence),transition_candidate_count=len(by_transition),
                thresholds=dict(search_distance_m=20,median_distance_m=12,max_direction_difference_deg=25,
                                road_overlap_min=.6,or_lane_overlap_min=.8,hd_endpoint_tolerance_m=.5,node_candidate_distance_m=15),
                deferred=['confirmed_HD_to_road_match','lane_direction_semantics','physical_lane_end','lane_change_intervals',
                          'RM2_lane_assignment','physical_junction_type','confirmed_merge_diverge'])
    return relations,info
