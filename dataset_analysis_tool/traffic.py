"""View-T group normalization and the stored Busan snapshot, kept separate."""
from collections import defaultdict
import json
import re
import warnings
import pandas as pd
import openpyxl
from common import RAW, js, status, read_csv

PERIODS = ['4시~10시','11시~17시','18시~24시']
VALUE_COLS = ['estimated_volume_total_raw','estimated_volume_car_raw','estimated_volume_bus_raw',
              'estimated_volume_truck_raw','mean_speed_kmh','congestion_frequency','congestion_time']
TRAFFIC_COLS = ['link_id','source','source_group_id','reference_year','day_type','period','observed_at',
                'estimated_volume_total_raw','estimated_volume_car_raw','estimated_volume_bus_raw',
                'estimated_volume_truck_raw','volume_unit','volume_per_hour','mean_speed_kmh',
                'congestion_frequency','congestion_time','density_proxy_veh_per_km',
                'observed_speed_raw','observed_speed_kmh','match_status','feature_status_json']

def text_cell(v):
    if v is None: return ''
    if isinstance(v,float) and v.is_integer(): return str(int(v))
    return str(v).strip()

def number(v):
    s=text_cell(v)
    if s in {'','-'}: return None
    x=float(s.replace(',',''))
    if x<0: raise ValueError('Unexpected negative traffic value')
    return x

def load_workbook(name):
    p=RAW/'view_t'/name
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore',message='Workbook contains no default style')
        wb=openpyxl.load_workbook(p,read_only=False,data_only=True)
    assert len(wb.sheetnames)==1
    ws=wb.active
    header_row=next(i for i in range(1,12) if text_cell(ws.cell(i,1).value)=='5.5 LINK ID')
    metadata='\n'.join(text_cell(ws.cell(i,1).value) for i in range(1,header_row))
    assert '2025년' in metadata and '부산광역시' in metadata and '기간 : 평일' in metadata
    top=[text_cell(ws.cell(header_row,j).value) for j in range(1,ws.max_column+1)]
    lower=[text_cell(ws.cell(header_row+1,j).value) for j in range(1,ws.max_column+1)]
    # Fill only horizontal merges in the actual upper header, never arbitrary blanks.
    for merge in ws.merged_cells.ranges:
        if merge.min_row==header_row and merge.max_row==header_row:
            for j in range(merge.min_col,merge.max_col+1): top[j-1]=top[merge.min_col-1]
    headers=[a+'/'+b if b else a for a,b in zip(top,lower)]
    assert len(headers)==len(set(headers))
    records=[];repeated_its_groups=[]
    for rownum,row in enumerate(ws.iter_rows(min_row=header_row+2,values_only=True),header_row+2):
        if all(v is None or text_cell(v)=='' for v in row): continue
        d=dict(zip(headers,[text_cell(v) for v in row]))
        assert d['5.5 LINK ID'].isdigit(), f'Unexpected group ID in {name}:{rownum}'
        assert '부산광역시' in d['권역']
        ids=[] if d['ITS LINK ID'] in {'','-'} else [x.strip() for x in d['ITS LINK ID'].split(',')]
        assert all(re.fullmatch(r'\d+',x) for x in ids)
        if len(ids)!=len(set(ids)):
            repeated_its_groups.append(dict(group_id=d['5.5 LINK ID'],extra_references=len(ids)-len(set(ids))))
        d['_its_ids']=ids;d['_row']=rownum;d['_file']=name;records.append(d)
    df=pd.DataFrame(records)
    assert df['5.5 LINK ID'].is_unique
    return df.set_index('5.5 LINK ID').to_dict('index'), dict(file=name,rows=len(df),metadata=metadata,headers=headers,merged_ranges=sorted(str(x) for x in ws.merged_cells.ranges),repeated_its_groups=repeated_its_groups)

def build_traffic(links):
    vol,vm=load_workbook('TrafficVolume(LINK).xlsx')
    speed,sm=load_workbook('AverageSpeed(LINK).xlsx')
    cong,cm=load_workbook('CongestIndex(LINK).xlsx')
    groups=[];mismatches=[]
    for gid in sorted(set(vol)|set(speed)|set(cong)):
        sources=[d[gid] for d in [vol,speed,cong] if gid in d]
        identity_ok=all(r['_its_ids']==sources[0]['_its_ids'] for r in sources)
        metadata_ok=all(all(r[k]==sources[0][k] for k in ['도로등급','도로명','권역','연장(km)','차선수']) for r in sources)
        group_status='consistent' if identity_ok and metadata_ok else 'source_identity_mismatch'
        if group_status!='consistent': mismatches.append(gid)
        relation_ids=sources[0]['_its_ids'] if identity_ok else sorted({x for row in sources for x in row['_its_ids']})
        base=dict(source_group_id=gid,reference_year='2025',day_type='weekday',
                  its_link_ids_json=js(relation_ids),road_name=sources[0]['도로명'],
                  source_length_km=number(sources[0]['연장(km)']),source_lane_count_raw=sources[0]['차선수'],
                  source_identity_status=group_status)
        if gid in vol or gid in speed:
            for period in PERIODS:
                row={**base,'period':period,**{c:None for c in VALUE_COLS}}
                refs=[]
                if gid in vol:
                    r=vol[gid];refs.append(dict(file=r['_file'],row=r['_row'],its_ids=r['_its_ids']))
                    for prefix,col in [('전체','total'),('승용차','car'),('버스','bus'),('트럭','truck')]:
                        row['estimated_volume_'+col+'_raw']=number(r[prefix+'-평일/'+period])
                if gid in speed:
                    r=speed[gid];refs.append(dict(file=r['_file'],row=r['_row'],its_ids=r['_its_ids']))
                    row['mean_speed_kmh']=number(r['전체-평일/'+period])
                row['source_refs_json']=js(refs)
                row['feature_status_json']=status('view_t','2025_weekday_Level5.5',group_status,{
                    'estimated_volume_total_raw':{'unit':'unconfirmed_period_aggregation','status':'estimate_raw'},
                    'estimated_volume_car_raw':{'unit':'unconfirmed_period_aggregation','status':'estimate_raw'},
                    'estimated_volume_bus_raw':{'unit':'unconfirmed_period_aggregation','status':'estimate_raw'},
                    'estimated_volume_truck_raw':{'unit':'unconfirmed_period_aggregation','status':'estimate_raw'},
                    'mean_speed_kmh':{'unit':'km/h','status':'annual_vehicle_speed_mean_not_snapshot'}})
                groups.append(row)
        if gid in cong:
            r=cong[gid]
            assert number(r['혼잡기대강도/평일']) in {0,None}
            row={**base,'period':'weekday_all',**{c:None for c in VALUE_COLS},
                 'congestion_frequency':number(r['혼잡빈도강도/평일']),'congestion_time':number(r['혼잡시간강도/평일']),
                 'source_refs_json':js([dict(file=r['_file'],row=r['_row'],its_ids=r['_its_ids'])])}
            row['feature_status_json']=status('view_t','2025_weekday_Level5.5',group_status,{
                'congestion_frequency':{'unit':'percent','status':'weekday_all'},
                'congestion_time':{'unit':'percent','status':'weekday_all','definition_document_year_range':'2019-2024'}})
            groups.append(row)
    group_df=pd.DataFrame(groups)
    lid=set(links.link_id);reverse=defaultdict(set);relation_rows=[]
    for r in groups:
        for link in dict.fromkeys(json.loads(r['its_link_ids_json'])):
            if link in lid:
                reverse[link,r['period']].add(r['source_group_id']);relation_rows.append((link,r))
    traffic=[]
    for link,r in relation_rows:
        conflict=len(reverse[link,r['period']])>1
        ok=r['source_identity_status']=='consistent' and not conflict
        match='ambiguous_multiple_groups' if conflict else ('exact_its_reference' if ok else 'ambiguous_source_identity')
        row={c:None for c in TRAFFIC_COLS}
        row.update(link_id=link,source='view_t',source_group_id=r['source_group_id'],reference_year='2025',
                   day_type='weekday',period=r['period'],match_status=match,
                   volume_unit='unconfirmed_period_aggregation' if r['period']!='weekday_all' else None)
        for c in VALUE_COLS: row[c]=r[c] if ok else None
        fields={c:{'status':('ambiguous_value_withheld' if not ok else ('source_missing' if r[c] is None else 'group_statistic_reference')),
                   'unit':'km/h' if c=='mean_speed_kmh' else ('percent' if c.startswith('congestion') else 'unconfirmed_period_aggregation')} for c in VALUE_COLS}
        fields.update(volume_per_hour={'status':'period_aggregation_unverified','unit':'veh/h'},
                      density_proxy_veh_per_km={'status':'volume_period_and_spatial_speed_definition_unverified','unit':'veh/km'},
                      observed_speed_raw={'status':'not_applicable'},observed_speed_kmh={'status':'not_applicable'})
        row['feature_status_json']=status('view_t','2025_weekday_Level5.5',match,fields,
                                         group_reference='view_t_groups.csv',independently_additive=False)
        traffic.append(row)
    api=RAW/'busan_link_traffic'
    manifest=json.loads((api/'COLLECTION_MANIFEST.json').read_text(encoding='utf-8'))
    observed=[];declared_total=set();page_numbers=[]
    for entry in manifest:
        p=(api/entry['response_file']).resolve();assert p.is_relative_to(api.resolve())
        j=json.loads(p.read_text(encoding='utf-8-sig'))
        assert j['resultCode']=='00' and entry['status']=='success'
        block=j['content'];data=block['items']
        assert len(data)==entry['row_count']
        declared_total.add(int(block['totalCount']));page_numbers.append(entry['query']['pageNo'])
        for i,r in enumerate(data):observed.append({**r,'_source':entry['response_file'],'_item_index':i})
    assert len(observed)==9270 and declared_total=={9270}
    assert page_numbers==list(range(1,94))
    ad=pd.DataFrame(observed).fillna('');assert not ad.duplicated(['lkId','statsDt']).any()
    # Check the adopted normalized CSV against the actual pages, not the old report.
    old=read_csv(api/'link.csv').sort_values(['lkId','statsDt']).reset_index(drop=True)
    check=ad.sort_values(['lkId','statsDt']).reset_index(drop=True)
    for col in ['lkId','statsDt','roadNm','bgngNodeNm','endNodeNm']: assert old[col].equals(check[col].astype(str))
    for col in ['spd','vol']: assert (pd.to_numeric(old[col])==pd.to_numeric(check[col])).all()
    for r in observed:
        if str(r['lkId']) not in lid: continue
        row={c:None for c in TRAFFIC_COLS}
        stamp=pd.Timestamp(r['statsDt'])
        if stamp.tzinfo is None:stamp=stamp.tz_localize('Asia/Seoul')
        row.update(link_id=str(r['lkId']),source='busan_link_traffic',source_group_id=str(r['lkId']),
                   period='snapshot',observed_at=stamp.isoformat(),observed_speed_raw=number(r['spd']),match_status='exact_id_snapshot')
        api_fields={c:{'status':'not_applicable_to_snapshot'} for c in VALUE_COLS}
        api_fields.update({
            'observed_speed_raw':{'unit':'unconfirmed','status':'observed_raw'},
            'observed_speed_kmh':{'unit':'km/h','status':'unit_unverified'},
            'observed_at':{'unit':'ISO8601','status':'source_time_assigned_Asia_Seoul'},
            'volume_per_hour':{'status':'vol_excluded_unknown_interval_and_zero_semantics'},
            'density_proxy_veh_per_km':{'status':'not_computed_snapshot'}})
        row['feature_status_json']=status('busan_link_traffic','collected_20261125','exact_id_snapshot',api_fields,
            source_ref=dict(file=r['_source'],item_index=r['_item_index']))
        traffic.append(row)
    traffic_df=pd.DataFrame(traffic,columns=TRAFFIC_COLS)
    info=dict(workbooks=[vm,sm,cm],groups_volume=len(vol),groups_speed=len(speed),groups_congestion=len(cong),
              group_identity_mismatches=mismatches,volume_only_groups=sorted(set(vol)-set(speed)),speed_only_groups=sorted(set(speed)-set(vol)),source_group_rows=len(group_df),
              ambiguous_links=len({l for (l,p),gs in reverse.items() if len(gs)>1}),
              ambiguous_links_by_period={p:len({l for (l,pp),gs in reverse.items() if pp==p and len(gs)>1}) for p in PERIODS+['weekday_all']},
              volume_unit='unconfirmed_period_aggregation',density_nonnull=0,api_pages=len(manifest),api_rows=len(ad),
              api_matched_rows=int(ad.lkId.isin(lid).sum()),api_unmatched_rows=int((~ad.lkId.isin(lid)).sum()),
              api_observed_at=sorted(ad.statsDt.unique()),api_speed_unit='unverified',
              api_legacy_csv_matches_raw=True,excluded_columns=['congestion_expectation','api_vol'],
              api_zero_volume_rows=int(pd.to_numeric(ad.vol).eq(0).sum()),
              all_source_its_ids=len({x for r in groups for x in json.loads(r['its_link_ids_json'])}),
              outside_network_its_ids=sorted({x for r in groups for x in json.loads(r['its_link_ids_json'])}-lid))
    volume_rows=group_df[group_df.period.isin(PERIODS)]
    cols=['estimated_volume_total_raw','estimated_volume_car_raw','estimated_volume_bus_raw','estimated_volume_truck_raw']
    numeric=volume_rows[cols].apply(pd.to_numeric,errors='coerce').dropna()
    difference=numeric[cols[0]]-numeric[cols[1:]].sum(axis=1)
    info['vehicle_component_total_check']=dict(comparable_group_periods=len(difference),nonzero_difference_rows=int(difference.ne(0).sum()),
                                               maximum_absolute_difference=float(difference.abs().max()),action='raw_values_preserved_not_reconciled')
    return traffic_df,group_df,info
