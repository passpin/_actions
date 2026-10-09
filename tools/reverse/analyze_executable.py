"""Read-only GD 2.2081 PE/RTTI analysis with version-specific Broma addresses.

Install development dependencies: pip install pefile capstone
This tool evaluates only the integer dispatch in createWithKey, never game code.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path
import capstone
from capstone.x86_const import X86_OP_REG, X86_OP_IMM, X86_OP_MEM
import pefile


def analyze(executable: Path, broma: dict, known_ids: list[int]) -> dict:
    blob = executable.read_bytes()
    expected_sha256='fc5a16c292278bc2e8e078fb1d5023c2bd658322dd72712767ea70c2dd9ec6d0'
    if hashlib.sha256(blob).hexdigest()!=expected_sha256:
        raise ValueError('This reviewed binary analysis targets GD 2.2081 SHA256 '+expected_sha256+'; review version-specific dispatch/serializer constants before analyzing another build.')
    pe = pefile.PE(data=blob)
    base = pe.OPTIONAL_HEADER.ImageBase
    image = pe.get_memory_mapped_image()
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    classes = broma['classes']
    method_at = {}
    for cls, spec in classes.items():
        for name, defs in spec['methods'].items():
            for definition in defs:
                rva = definition.get('win')
                if rva and rva.startswith('0x'):
                    method_at[int(rva,16)] = (cls,name)
    bounds = {r.struct.BeginAddress:r.struct.EndAddress for r in pe.DIRECTORY_ENTRY_EXCEPTION}
    for runtime_function in pe.DIRECTORY_ENTRY_EXCEPTION:
        unwind=runtime_function.unwindinfo
        if getattr(unwind,'Flags',0)&4:
            primary=getattr(unwind,'FunctionEntry',None)
            if primary in bounds:bounds[primary]=max(bounds[primary],runtime_function.struct.EndAddress)
    factory_rva = int(classes['GameObject']['methods']['createWithKey'][0]['win'],16)
    factory_end = bounds[factory_rva]
    instructions = {i.address-base:i for i in md.disasm(image[factory_rva:factory_end],base+factory_rva)}

    def rtti(vtable: int) -> str | None:
        try:
            col = struct.unpack_from('<Q',image,vtable-base-8)[0]-base
            if not (0 < col < len(image)-24): return None
            sig,_,_,type_rva,_,self_rva = struct.unpack_from('<6I',image,col)
            if sig != 1 or self_rva != col: return None
            name = image[type_rva+16:].split(b'\0',1)[0].decode('ascii')
            if name.startswith('.?AV') and name.endswith('@@'):
                return name[4:-2]
        except (ValueError,struct.error,UnicodeError):
            return None
        return None

    # Canonicalize register aliases; 32-bit writes zero-extend on x64.
    def reg(i, number):
        n=i.reg_name(number)
        aliases={'eax':'rax','ax':'rax','al':'rax','ecx':'rcx','cx':'rcx','cl':'rcx','edx':'rdx','dx':'rdx','dl':'rdx','ebx':'rbx','bx':'rbx','bl':'rbx','esi':'rsi','edi':'rdi','ebp':'rbp','esp':'rsp'}
        if n.startswith('r') and n[-1:] in {'d','w','b'} and n[1:-1].isdigit(): return n[:-1]
        return aliases.get(n,n)

    def trace(oid):
        # At this point the factory has validated the frame-name lookup and starts ID dispatch.
        pc=factory_rva+0x62
        regs={'r14':oid,'r15':2**64-1,'rip':0}
        comparison=None
        last_constructor=None
        path=[]
        for _ in range(2500):
            i=instructions.get(pc)
            if i is None:return None, {'reason':'instruction_not_decoded','rva':hex(pc)}
            path.append(pc)
            regs['rip']=base+pc+i.size
            def val(op, address=False):
                if op.type==X86_OP_IMM:return op.imm
                if op.type==X86_OP_REG:return regs.get(reg(i,op.reg))
                if op.type==X86_OP_MEM:
                    m=op.mem
                    a=regs.get(reg(i,m.base),0) if m.base else 0
                    idx=regs.get(reg(i,m.index),0) if m.index else 0
                    if a is None or idx is None:return None
                    address_value=a+idx*m.scale+m.disp
                    if address:return address_value
                    offset=address_value-base
                    if 0<=offset<=len(image)-op.size:return int.from_bytes(image[offset:offset+op.size],'little')
                return None
            ops=i.operands
            m=i.mnemonic
            next_pc=pc+i.size
            if m in {'mov','movzx','movsxd','movsx','lea'} and len(ops)==2:
                v=val(ops[1],m=='lea')
                if v is not None and m in {'movsxd','movsx'} and v & (1<<(ops[1].size*8-1)):v-=1<<(ops[1].size*8)
                if ops[0].type==X86_OP_REG:
                    regs[reg(i,ops[0].reg)]=v
                    if v is not None and ops[0].size==4:regs[reg(i,ops[0].reg)]=v&0xffffffff
                elif ops[0].type==X86_OP_MEM and v is not None:
                    cls=rtti(v)
                    if cls and cls in classes:
                        return cls, {'confidence':'confirmed','basis':'factory dispatch plus PE RTTI vtable','factory_rva':hex(factory_rva),'vtable_rva':hex(v-base),'assignment_rva':hex(pc),'dispatch_path_rvas':[hex(x) for x in path]}
            elif m in {'cmp','test'}:
                a,b=val(ops[0]),val(ops[1])
                comparison=(a,b,ops[0].size*8,m)
            elif m=='jmp':
                target=val(ops[0])
                if target is None:return None,{'reason':'unknown_jump_target','rva':hex(pc)}
                next_pc=target-base
            elif m.startswith('j'):
                if comparison is None or comparison[0] is None or comparison[1] is None:
                    if last_constructor and m in {'je','jz'} and comparison and comparison[3]=='test':
                        # The only remaining unresolved factory paths are the shared
                        # EffectGameObject allocation-success test. Record the constructor
                        # only after dispatch reached its allocation test; no derived
                        # vtable override occurs on this common terminal path.
                        reviewed_terminal_paths={0x18d246:'EffectGameObject',0x18d1b3:'EnhancedGameObject',0x18d03f:'SFXTriggerGameObject',0x18c6eb:'AdvancedFollowTriggerObject'}
                        if reviewed_terminal_paths.get(pc)==last_constructor[0]:
                            return last_constructor[0],{'confidence':'confirmed','basis':'factory terminal allocation path calls Broma constructor','constructor_rva':hex(last_constructor[1]),'allocation_test_rva':hex(pc),'dispatch_path_rvas':[hex(x) for x in path]}
                    return None,{'reason':'branch_depends_on_non_dispatch_state','rva':hex(pc)}
                a,b,bits,kind=comparison
                mask=(1<<bits)-1;a&=mask;b&=mask
                signed=lambda n:n-(1<<bits) if n&(1<<(bits-1)) else n
                z=(a&b)==0 if kind=='test' else a==b
                choices={'je':z,'jz':z,'jne':not z,'jnz':not z,'ja':a>b,'jae':a>=b,'jb':a<b,'jbe':a<=b,'jg':signed(a)>signed(b),'jge':signed(a)>=signed(b),'jl':signed(a)<signed(b),'jle':signed(a)<=signed(b)}
                if m not in choices:return None,{'reason':'unsupported_branch','rva':hex(pc),'mnemonic':m}
                if choices[m]:next_pc=val(ops[0])-base
            elif m=='call':
                target=val(ops[0])
                method=method_at.get(target-base) if target is not None else None
                if method and method[1]==method[0]:last_constructor=(method[0],target-base)
                if method and method[1] in {'create','createWithFrame','createWithKey'} and ('Object' in method[0] or 'Trigger' in method[0]):
                    return method[0],{'confidence':'confirmed','basis':'factory dispatch calls Broma-bound constructor','call_rva':hex(pc),'callee_rva':hex(target-base),'dispatch_path_rvas':[hex(x) for x in path]}
                # A call clobbers volatile registers; object ID is in callee-saved r14.
                for n in ['rax','rcx','rdx','r8','r9','r10','r11']:regs[n]=None
            elif m in {'add','sub','and','or','xor','shl','shr','sar','imul'} and ops and ops[0].type==X86_OP_REG:
                n=reg(i,ops[0].reg);a=regs.get(n);b=val(ops[-1])
                if m=='xor' and ops[-1].type==X86_OP_REG and reg(i,ops[-1].reg)==n:regs[n]=0
                elif a is not None and b is not None:
                    calc={'add':lambda:a+b,'sub':lambda:a-b,'and':lambda:a&b,'or':lambda:a|b,'xor':lambda:a^b,'shl':lambda:a<<b,'shr':lambda:a>>b,'sar':lambda:a>>b,'imul':lambda:a*b}
                    regs[n]=calc[m]()&((1<<(ops[0].size*8))-1)
                else:regs[n]=None
            elif m in {'cdqe','cltq'}:
                v=regs.get('rax');regs['rax']=v-(1<<32) if v is not None and v&(1<<31) else v
            elif m=='ret':return None,{'reason':'returned_without_class','rva':hex(pc)}
            pc=next_pc
        return None,{'reason':'trace_limit'}

    mapping={}; unresolved={}
    for oid in sorted(set(known_ids)):
        cls,evidence=trace(oid)
        if cls:mapping[str(oid)]={'class':cls,**evidence}
        else:unresolved[str(oid)]=evidence
    property_fields={}
    for cls,spec in classes.items():
        for p in spec['properties']:
            property_fields.setdefault(str(p['key']),[]).append({'class':cls,**p,'source':'geode-2.2081','confidence':'confirmed','claim':'Broma annotated member field; object support requires factory/class/parser evidence'})
    def analyze_method(cls,name,rva):
        end=bounds.get(rva)
        if end is None:return {'rva':hex(rva),'complete':False,'reason':'no PE unwind function bounds'}
        regs=({'rcx':('this',0),'rdx':('values_vector',0),'r8':('exists_vector',0)} if name=='customObjectSetup'
              else {'rcx':('values_vector',0),'rdx':('exists_vector',0)} if name=='objectFromVector' else {})
        reads={};writes={};stores={};called=[];disassembly=[];current_key=None
        for i in md.disasm(image[rva:end],base+rva):
            ops=i.operands;m=i.mnemonic;pc=i.address-base
            disassembly.append(f'{pc:08x}: {m} {i.op_str}')
            for op in ops:
                if op.type==X86_OP_MEM and op.mem.base:
                    pointer=regs.get(reg(i,op.mem.base))
                    if pointer and pointer[0]=='exists_data' and not op.mem.index:
                        offset=pointer[1]+op.mem.disp
                        if offset>=0 and offset%8==0 and 0<offset//8<1024:
                            current_key=offset//8
                            reads.setdefault(str(offset//8),[]).append({'rva':hex(pc),'instruction':f'{m} {i.op_str}','basis':'property-presence vector indexed by key * sizeof(void*)','confidence':'confirmed'})
            if name in {'customObjectSetup','objectFromVector'} and current_key is not None and ops and ops[0].type==X86_OP_MEM and ops[0].mem.base and m in {'mov','movss','movsd','movups','movaps'}:
                pointer=regs.get(reg(i,ops[0].mem.base))
                if pointer and pointer[0]=='this' and not ops[0].mem.index:
                    fields=[p for p in classes[cls]['properties'] if p['key']==current_key]
                    stores.setdefault(str(current_key),[]).append({'rva':hex(pc),'field_offset':hex(pointer[1]+ops[0].mem.disp),'store_width':ops[0].size,'instruction':f'{m} {i.op_str}',
                        'broma_fields':[{'field':p['field'],'cpp_type':p['cpp_type'],'line':p['line']} for p in fields],
                        'confidence':'inferred','basis':'member store following property-presence access; value flow and conditions require verification'})
            if m=='mov' and len(ops)==2 and ops[0].type==X86_OP_REG:
                n=reg(i,ops[0].reg);source=ops[1]
                if source.type==X86_OP_REG:regs[n]=regs.get(reg(i,source.reg))
                elif source.type==X86_OP_MEM and source.mem.base and not source.mem.index:
                    pointer=regs.get(reg(i,source.mem.base))
                    if pointer and source.mem.disp==0 and pointer[0] in {'exists_vector','values_vector'}:
                        regs[n]=(pointer[0].replace('_vector','_data'),0)
                    else:regs[n]=None
                elif source.type==X86_OP_IMM:
                    regs[n]=('integer',source.imm)
                else:regs[n]=None
            elif m=='lea' and len(ops)==2 and ops[0].type==X86_OP_REG:
                n=reg(i,ops[0].reg);source=ops[1]
                pointer=regs.get(reg(i,source.mem.base)) if source.mem.base else None
                if pointer and not source.mem.index:regs[n]=(pointer[0],pointer[1]+source.mem.disp)
                else:regs[n]=None
            elif m in {'add','sub'} and len(ops)==2 and ops[0].type==X86_OP_REG and ops[1].type==X86_OP_IMM:
                n=reg(i,ops[0].reg);pointer=regs.get(n)
                if pointer:regs[n]=(pointer[0],pointer[1]+ops[1].imm*(1 if m=='add' else -1))
            elif m=='call':
                target=None
                if ops[0].type==X86_OP_IMM:target=ops[0].imm-base
                elif ops[0].type==X86_OP_MEM and i.reg_name(ops[0].mem.base)=='rip':target=pc+i.size+ops[0].mem.disp
                method=method_at.get(target)
                if method:called.append({'class':method[0],'method':method[1],'rva':hex(pc),'target_rva':hex(target)})
                # libcocos2d exported stringstream integer insertion. An immediate
                # streamed integer is a serializer-key candidate, not automatically
                # a property: numeric values can also be constants.
                edx=regs.get('rdx')
                if name=='getSaveString' and target==0x516d20 and edx and edx[0]=='integer' and 0<edx[1]<1024:
                    writes.setdefault(str(edx[1]),[]).append({'rva':hex(pc),'basis':'immediate integer passed to stringstream insertion','confidence':'inferred','requires':'match to parser presence access or Broma field annotation'})
                for n in ['rax','rcx','rdx','r8','r9','r10','r11']:regs[n]=None
        return {'rva':hex(rva),'end_rva':hex(end),'complete':False,'completeness_note':'recognized direct accesses only; branches, helper calls and object-ID conditions require review',
                'property_read_accesses':reads,'property_write_candidates':writes,'property_field_store_candidates':stores,'calls':called,'disassembly':disassembly}
    class_access={}
    for cls,spec in classes.items():
        methods={}
        for name in ['customObjectSetup','getSaveString']:
            for definition in spec['methods'].get(name,[]):
                rva=definition.get('win')
                if rva and rva.startswith('0x'):methods[name]=analyze_method(cls,name,int(rva,16))
        if methods:class_access[cls]={'bases':spec['bases'],'methods':methods}
    # GameObject's generic parser is static rather than its inline virtual setup.
    definition=classes['GameObject']['methods']['objectFromVector'][0]
    class_access['GameObject']['methods']['objectFromVector']=analyze_method('GameObject','objectFromVector',int(definition['win'],16))
    return {'format':'gmdtool-executable-evidence-v1','game_version':'2.2081','executable_sha256':hashlib.sha256(blob).hexdigest(),'pe_image_base':hex(base),
            'factory_rva':hex(factory_rva),'object_id_to_class':mapping,'unresolved_object_ids':unresolved,'property_key_to_field_type':property_fields,'class_property_access':class_access}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('executable',type=Path);p.add_argument('broma_index',type=Path);p.add_argument('known_ids',type=Path);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    result=analyze(args.executable,json.loads(args.broma_index.read_text(encoding='utf8')),json.loads(args.known_ids.read_text(encoding='utf8'))['object_ids'])
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(f"mapped={len(result['object_id_to_class'])} unresolved={len(result['unresolved_object_ids'])}")


if __name__=='__main__':main()
