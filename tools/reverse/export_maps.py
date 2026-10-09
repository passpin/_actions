"""Export reviewable maps from executable/Broma evidence without guessing support."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def export(evidence_path: Path,broma_path: Path,catalog_path: Path,out: Path) -> dict:
    evidence=json.loads(evidence_path.read_text(encoding='utf8'))
    broma=json.loads(broma_path.read_text(encoding='utf8'))
    catalog=json.loads(catalog_path.read_text(encoding='utf8'))
    classes=broma['classes']
    used_classes={o['class'] for o in evidence['object_id_to_class'].values()}
    def ancestors(cls,seen=None):
        seen=set() if seen is None else seen
        if cls in seen:return []
        seen.add(cls)
        out=[cls]
        for base in classes.get(cls,{}).get('bases',[]):
            out.extend(ancestors(base,seen))
        return out
    reads={}
    for cls in sorted(used_classes):
        keys={}
        for ancestor in ancestors(cls):
            methods=evidence['class_property_access'].get(ancestor,{}).get('methods',{})
            for method in ('customObjectSetup','objectFromVector'):
                for key,accesses in methods.get(method,{}).get('property_read_accesses',{}).items():
                    keys.setdefault(key,[]).extend({'declaring_class':ancestor,'method':method,**p} for p in accesses)
        reads[cls]={'property_keys':sorted(map(int,keys)),'accesses':keys,'confidence':'confirmed',
                    'claim':'recognized direct parser presence accesses, including inherited/static base parser; union of conditional branches',
                    'complete_schema':False}
    assignments={k:{'class':v['class'],'confidence':v['confidence'],'basis':v['basis'],
                    'factory_rva':evidence['factory_rva'],'details':{x:y for x,y in v.items() if x not in {'class','confidence','basis','dispatch_path_rvas'}}}
                 for k,v in evidence['object_id_to_class'].items()}
    conflicts=[];unverified=[];compatible_count=0
    # A primitive field mismatch is a useful conflict; complex members such as
    # group/string-presence flags are not identical to the wire property's type.
    kind={'bool':'bool','float':'real','double':'real','int':'int','short':'int'}
    integer_types={'int','enum','group_id','item_id','control_id'}
    for obj in catalog['objects']:
        cls=evidence['object_id_to_class'].get(str(obj['id']),{}).get('class')
        if not cls:continue
        annotations={}
        for ancestor in ancestors(cls):
            for p in classes.get(ancestor,{}).get('properties',[]):
                annotations.setdefault(p['key'],[]).append({'class':ancestor,**p})
        for prop in obj['properties']:
            expected='int' if prop['type'] in integer_types else prop['type']
            matching=annotations.get(prop['key'],[])
            scalar=[p for p in matching if p['cpp_type'] in kind]
            if prop['type'] in {'raw','particle','text','groups','weighted_groups','sequence','remap_list'}:
                continue
            if scalar and any(kind[p['cpp_type']]==expected for p in scalar):compatible_count+=1
            elif scalar:
                conflicts.append({'object_id':obj['id'],'cpp_class':cls,'property':prop,'broma':scalar,
                                  'status':'requires direct parser value-conversion review; member type and wire type can differ'})
            elif not matching:
                unverified.append({'object_id':obj['id'],'key':prop['key'],'name':prop['name'],'type':prop['type'],
                                   'reason':'no inherited Broma field annotation; no automatic confidence promotion'})
    out.mkdir(parents=True,exist_ok=True)
    def write(name,data):
        (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    write('object-classes.json',{'format':'gmdtool-object-class-map-v1','game_version':'2.2081','executable_sha256':evidence['executable_sha256'],
                               'object_count':len(assignments),'class_count':len(used_classes),'object_id_to_class':assignments,'unresolved':evidence['unresolved_object_ids']})
    write('class-read-sets.json',{'format':'gmdtool-class-read-sets-v1','game_version':'2.2081','classes':reads})
    write_path=evidence_path.parent/'write-sets-2.2081.json'
    verified=json.loads(write_path.read_text(encoding='utf8')) if write_path.exists() else None
    implementation_fields={}
    header_fields={}
    writes={}
    if verified:
        for cls in sorted(used_classes):
            access={}
            for ancestor in ancestors(cls):
                serializer=verified['classes'].get(ancestor,{})
                for record in serializer.get('verified_writes',[]):
                    access.setdefault(str(record['key']),[]).append({'declaring_class':ancestor,**record})
            writes[cls]={'property_keys':sorted(map(int,access)),'accesses':access,'confidence':'confirmed',
                         'claim':'verified comma/key/comma/value serializer writes, including inherited serializers; union of conditional branches',
                         'serializer_extraction_complete':all(verified['classes'].get(a,{}).get('complete',True) for a in ancestors(cls)),
                         'complete_schema':False}
        for cls,serializer in verified['classes'].items():
            for field in serializer.get('verified_property_fields',[]):
                target=implementation_fields if isinstance(field['key'],int) else header_fields
                target.setdefault(str(field['key']),[]).append({'class':cls,**field})
        write('class-write-sets.json',{'format':'gmdtool-class-write-sets-v1','game_version':'2.2081','classes':writes,
                                     'numeric_extraction_audit':verified.get('statistics',{}),'schema_completeness':False})
    write('property-fields.json',{'format':'gmdtool-property-fields-v1','game_version':'2.2081','property_key_count':len(evidence['property_key_to_field_type']),
                                 'annotated_field_count':sum(map(len,evidence['property_key_to_field_type'].values())),'properties':evidence['property_key_to_field_type'],
                                 'implementation_property_fields':implementation_fields,'header_property_fields':header_fields})
    report={'format':'gmdtool-implementation-catalog-report-v1','object_id_mappings':len(assignments),'factory_classes':len(used_classes),
            'confirmed_parser_class_key_pairs':sum(len(v['property_keys']) for v in reads.values()),'compatible_scalar_declarations':compatible_count,
            'verified_serializer_class_key_pairs':sum(len(v['property_keys']) for v in writes.values()),
            'verified_property_field_records':sum(map(len,implementation_fields.values())),
            'verified_header_field_records':sum(map(len,header_fields.values())),
            'scalar_type_conflicts':conflicts,'unverified_field_annotations':unverified,
            'policy':'Class-level union of parser accesses does not establish per-Object-ID property support; no schema confidence is promoted automatically.'}
    write('catalog-conflicts.json',report)
    return {k:v for k,v in report.items() if isinstance(v,int)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence',type=Path,default=ROOT/'tools/reverse/evidence/executable-2.2081.json')
    p.add_argument('--broma',type=Path,default=ROOT/'tools/reverse/evidence/broma-2.2081.json')
    p.add_argument('--catalog',type=Path,default=ROOT/'data/compiled/catalog.normalized.json')
    p.add_argument('--out',type=Path,default=ROOT/'tools/reverse/evidence/maps')
    a=p.parse_args();print(json.dumps(export(a.evidence,a.broma,a.catalog,a.out),sort_keys=True))


if __name__=='__main__':main()
