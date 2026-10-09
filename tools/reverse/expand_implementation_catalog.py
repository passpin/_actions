"""Add conservative schemas from reviewed, unconditional class parsers.

Only classes whose member interpretation is independent of Object ID are used.
Shared EffectGameObject/EnterEffectObject fields are deliberately not expanded:
their parser branches depend on Object ID and property state.
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SAFE_CLASSES={'EnhancedGameObject','SmartGameObject','ForceBlockGameObject','CheckpointGameObject','RingObject'}


def expand(data: Path,evidence: Path,broma: Path) -> dict:
    facts=json.loads(evidence.read_text(encoding='utf8'))
    classes=json.loads(broma.read_text(encoding='utf8'))['classes']
    index=json.loads((data/'catalog.json').read_text(encoding='utf8'))
    filename='objects/implementation_objects.json'
    existing={o['id'] for relative in index['object_files'] if relative!=filename for o in json.loads((data/relative).read_text(encoding='utf8'))['objects']}
    objects=[]
    for oid,spec in facts['object_id_to_class'].items():
        oid=int(oid);cls=spec['class']
        if oid in existing or cls not in SAFE_CLASSES:continue
        methods=facts['class_property_access'][cls]['methods']
        reads=methods['customObjectSetup'].get('property_read_accesses',{})
        properties=[]
        for p in classes[cls]['properties']:
            if str(p['key']) not in reads:continue
            kind={'bool':'bool','float':'real','double':'real','int':'int','short':'int'}.get(p['cpp_type'])
            if kind is None:continue
            name=p['field'][2:]
            name=re.sub(r'([a-z0-9])([A-Z])',r'\1_\2',name).lower()
            properties.append({'key':p['key'],'name':name,'type':kind,'sources':['geode-2.2081','executable-2.2081'],
                               'confidence':'confirmed','implementation_evidence':{'class':cls,'field':p['field'],'cpp_type':p['cpp_type'],'broma_line':p['line'],
                               'parser_rva':methods['customObjectSetup']['rva'],'presence_accesses':reads[str(p['key'])]}})
        if not properties:continue
        objects.append({'id':oid,'name':f'{cls} {oid}','base':'object','cpp_class':cls,'tags':['object','implementation-backed'],
                        'sources':['fixture-object-ids','geode-2.2081','executable-2.2081'],'confidence':'confirmed','complete_schema':False,
                        'notes':'Serialized ID and C++ class verified; name is a class label, not an editor display name. Only annotated primitive fields with direct parser accesses are typed.',
                        'properties':properties})
    objects.sort(key=lambda o:o['id'])
    result={'$schema':'../schema/object-catalog.schema.json','schema_version':1,'category':'implementation-verified-objects','objects':objects}
    (data/filename).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    if filename not in index['object_files']:
        index['object_files'].append(filename);index['object_files'].sort()
        (data/'catalog.json').write_text(json.dumps(index,indent=2)+'\n',encoding='utf8')
    return {'added_schemas':len(objects),'confirmed_property_declarations':sum(len(o['properties']) for o in objects),'classes':sorted(SAFE_CLASSES)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,default=ROOT/'data')
    p.add_argument('--evidence',type=Path,default=ROOT/'tools/reverse/evidence/executable-2.2081.json')
    p.add_argument('--broma',type=Path,default=ROOT/'tools/reverse/evidence/broma-2.2081.json')
    a=p.parse_args();print(json.dumps(expand(a.data,a.evidence,a.broma),sort_keys=True))


if __name__=='__main__':main()
