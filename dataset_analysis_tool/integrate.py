"""Offline entry point. Build into an explicit new directory, then reread/validate.

Deployment and archival are separate operations: this command never deletes or
overwrites a populated output directory or any raw source.
"""
import argparse
import json
from pathlib import Path
from common import ROOT, dump, verify_sources, write_csv
from network import build_network
from traffic import build_traffic
from hd_map import build_hd
from validate import validate

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'data/processed')
    parser.add_argument('--report',type=Path,default=ROOT/'docs/도로_데이터셋_통합_검증.json')
    parser.add_argument('--validate-only',action='store_true')
    args=parser.parse_args();output=args.output.resolve()
    if args.report.resolve().is_relative_to((ROOT/'data/raw').resolve()):raise SystemExit('Cannot write report under raw sources')
    if args.validate_only:
        previous=json.loads(args.report.read_text(encoding='utf-8')) if args.report.exists() else {}
        report=validate(output,previous.get('source_hashes'))
        previous.update(report)
        report=previous
        dump(args.report,report)
        print('VALIDATION PASSED', {k:v['rows'] for k,v in report['tables'].items()},flush=True)
        return
    if output.exists() and any(output.iterdir()):raise SystemExit('Output must be new or empty; use --validate-only to check existing deliverables.')
    if output.is_relative_to((ROOT/'data/raw').resolve()):raise SystemExit('Cannot write under raw sources')
    output.mkdir(parents=True,exist_ok=True)
    sources=verify_sources();print(f'Source files verified: {len(sources)}',flush=True)
    links,nodes,trans,projected,network=build_network();print('National network built',flush=True)
    traffic,groups,traffic_info=build_traffic(links);print('Traffic sources normalized',flush=True)
    hd,hd_info=build_hd(links,nodes,trans,projected);print('HD candidates evaluated',flush=True)
    for name,frame in [('road_nodes',nodes),('road_links',links),('road_transitions',trans),('road_traffic',traffic),
                       ('view_t_groups',groups),('hd_lane_link_matches',hd)]:
        write_csv(output/(name+'.csv'),frame)
    report=validate(output,sources)
    report.update(network=network,traffic=traffic_info,hd=hd_info,
                  contract_date='2026-11-26',source_policy='four_selected_raw_directories_offline_only',
                  pipeline_version='1',publication='local_only_redistribution_not_approved')
    dump(args.report,report)
    print('BUILD AND VALIDATION PASSED', {k:v['rows'] for k,v in report['tables'].items()},flush=True)

if __name__=='__main__':main()
