"""Verify GD serializer keys from imported fmt::BasicWriter operations.

This is development-only, read-only PE analysis. It does not execute game code.
Unlike immediate-key candidates, a verified key must occur between real comma
insertions and a real value insertion on the same writer. Constant value tokens
(notably boolean 1) are consumed as values and cannot become additional keys.
Registers and stack BasicStringRef temporaries retain value/member provenance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import capstone
import pefile
from capstone.x86_const import X86_OP_IMM, X86_OP_MEM, X86_OP_REG


def alias(name: str) -> str:
    aliases = {'eax': 'rax', 'ax': 'rax', 'al': 'rax', 'ah': 'rax', 'ecx': 'rcx', 'cx': 'rcx', 'cl': 'rcx',
               'edx': 'rdx', 'dx': 'rdx', 'dl': 'rdx', 'ebx': 'rbx', 'bx': 'rbx', 'bl': 'rbx',
               'esi': 'rsi', 'si': 'rsi', 'sil': 'rsi', 'edi': 'rdi', 'di': 'rdi', 'dil': 'rdi',
               'ebp': 'rbp', 'bp': 'rbp', 'bpl': 'rbp', 'esp': 'rsp', 'sp': 'rsp', 'spl': 'rsp'}
    return aliases.get(name, re.sub(r'^(r\d+)[dwb]$', r'\1', name))


def add(value, offset):
    if isinstance(value, int): return value + offset
    if isinstance(value, tuple) and value[0] == 'address': return ('address', value[1], value[2] + offset)
    if value is not None: return ('add', value, offset)
    return None


def fields(value):
    if not isinstance(value, tuple): return []
    result = []
    if value[0] == 'field': result.append({'field_offset': hex(value[1]), 'width': value[2], 'load_rva': hex(value[3])})
    elif value[0] == 'address' and value[1] == 'this': result.append({'field_offset': hex(value[2]), 'width': None, 'load_rva': None, 'kind': 'member address'})
    for nested in value[1:]:
        if isinstance(nested, tuple): result.extend(fields(nested))
    return list({json.dumps(item, sort_keys=True): item for item in result}.values())


def nested_writers(value):
    if not isinstance(value, tuple): return []
    own = [value[1]] if value[0] == 'writer_text' else []
    return own + [writer for member in value[1:] for writer in nested_writers(member)]


def base_serializer(value):
    if not isinstance(value, tuple): return None
    if value[0] == 'call_result' and len(value) >= 3 and value[2] == 'getSaveString': return value[1]
    return next((owner for member in value[1:] if (owner := base_serializer(member))), None)


class Analyzer:
    def __init__(self, executable: Path, evidence: dict, broma: dict):
        self.blob = executable.read_bytes()
        self.pe = pefile.PE(data=self.blob)
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        self.image = self.pe.get_memory_mapped_image()
        self.evidence = evidence
        if hashlib.sha256(self.blob).hexdigest() != evidence['executable_sha256']:
            raise ValueError('Executable hash differs from the input evidence; regenerate evidence for this exact binary.')
        self.broma = broma
        self.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        self.md.detail = True
        self.imports = {item.address - self.base: (item.name or b'').decode('ascii', errors='replace')
                        for dll in self.pe.DIRECTORY_ENTRY_IMPORT for item in dll.imports}
        self.method_at = {int(method['rva'], 16): (cls, name)
                          for cls, info in evidence['class_property_access'].items()
                          for name, method in info['methods'].items()}

    def literal(self, value):
        if not isinstance(value, int): return None
        rva = value - self.base
        if not 0 <= rva < len(self.image): return None
        raw = self.image[rva:rva + 256].split(b'\0', 1)[0]
        try: return raw.decode('ascii')
        except UnicodeDecodeError: return None

    def analyze(self, cls, method):
        start, end = int(method['rva'], 16), int(method['end_rva'], 16)
        instructions = list(self.md.disasm(self.image[start:end], self.base + start))
        regs = {'rcx': ('address', 'this', 0), 'rsp': ('address', 'stack', 0)}
        memory, events, base_calls, guards = {}, [], [], []
        constructors = set()
        snapshots = {}
        pending_string_paths = {}

        for instruction in instructions:
            ops, mnemonic = instruction.operands, instruction.mnemonic
            rva = instruction.address - self.base
            # Preserve constructed string provenance across a forward branch
            # whose alternate path initializes the same temporary to empty.
            for incoming in pending_string_paths.get(instruction.address, []):
                for at, value in incoming.items():
                    if nested_writers(value) and memory.get(at) != value:
                        memory[at] = ('choice', memory.get(at), value)
            snapshots[rva] = (dict(regs), dict(memory))
            rn = lambda number: alias(instruction.reg_name(number))

            def address(op):
                if op.type != X86_OP_MEM: return None
                m = op.mem
                base = instruction.address + instruction.size if m.base and rn(m.base) == 'rip' else regs.get(rn(m.base)) if m.base else 0
                index = regs.get(rn(m.index)) if m.index else 0
                if not isinstance(index, int): return None
                return add(base, m.disp + index * m.scale)

            def read(op):
                if op.type == X86_OP_IMM: return op.imm
                if op.type == X86_OP_REG: return regs.get(rn(op.reg))
                at = address(op)
                if isinstance(at, tuple) and at[:2] == ('address', 'this'):
                    return ('field', at[2], op.size, rva)
                if at in memory: return memory[at]
                if isinstance(at, tuple) and at[0] == 'add': return ('dereference', at, op.size, rva)
                if isinstance(at, int) and 0 <= at - self.base <= len(self.image) - op.size:
                    return int.from_bytes(self.image[at - self.base:at - self.base + op.size], 'little')
                return ('dereference', at, op.size, rva) if at is not None else None

            def write(op, value):
                if op.type == X86_OP_REG: regs[rn(op.reg)] = value
                elif op.type == X86_OP_MEM:
                    at = address(op)
                    if at is not None: memory[at] = value

            if mnemonic in {'mov', 'movzx', 'movsx', 'movsxd', 'movss', 'movsd', 'movaps', 'movups', 'movdqa', 'movdqu', 'movd', 'movq'} and len(ops) == 2:
                write(ops[0], read(ops[1]))
            elif mnemonic == 'lea' and len(ops) == 2: write(ops[0], address(ops[1]))
            elif mnemonic == 'push': regs['rsp'] = add(regs.get('rsp'), -8)
            elif mnemonic == 'pop':
                if ops: write(ops[0], None)
                regs['rsp'] = add(regs.get('rsp'), 8)
            elif mnemonic in {'xor', 'xorps', 'pxor'} and len(ops) == 2 and ops[0].type == ops[1].type == X86_OP_REG and rn(ops[0].reg) == rn(ops[1].reg): write(ops[0], 0)
            elif mnemonic in {'add', 'sub'} and len(ops) == 2:
                a, b = read(ops[0]), read(ops[1])
                write(ops[0], add(a, b if mnemonic == 'add' else -b) if isinstance(b, int) else ('arithmetic', a, b))
            elif mnemonic.startswith(('cvt', 'vcvt')) and len(ops) >= 2:
                write(ops[0], ('conversion', mnemonic, read(ops[-1])))
            elif mnemonic in {'cmp', 'test', 'ucomiss', 'comiss', 'ucomisd', 'comisd'}:
                sources = [field for op in ops for field in fields(read(op))]
                if sources: guards.append({'rva': hex(rva), 'instruction': mnemonic + ' ' + instruction.op_str, 'fields': sources})
            elif mnemonic == 'jmp' and ops[0].type == X86_OP_IMM and ops[0].imm > instruction.address:
                pending_string_paths.setdefault(ops[0].imm, []).append(dict(memory))
            elif mnemonic == 'call':
                target = address(ops[0]) if ops[0].type == X86_OP_MEM else read(ops[0])
                import_name = self.imports.get(target - self.base) if isinstance(target, int) else None
                writer = regs.get('rcx')
                argument = regs.get('rdx')
                result = None
                if import_name and 'BasicWriter' in import_name:
                    if import_name.startswith('??0'):
                        constructors.add(repr(writer))
                        result = writer
                    elif import_name.startswith('??6'):
                        kind = 'string' if 'BasicStringRef' in import_name else 'real' if import_name.endswith('N@Z') else 'int'
                        if kind == 'real': argument = regs.get('xmm1')
                        elif kind == 'string': argument = memory.get(argument, argument)
                        events.append({'rva': hex(rva), 'kind': kind, 'writer': repr(writer), 'value': argument,
                                       'literal': self.literal(argument) if kind == 'string' else None,
                                       'import_rva': hex(target - self.base), 'import': import_name,
                                       'guard': guards[-1] if guards else None})
                        result = writer
                    elif 'c_str' in import_name: result = ('writer_text', repr(writer))
                elif import_name and 'BasicStringRef' in import_name and import_name.startswith('??0'):
                    memory[writer] = memory.get(argument, argument)
                    result = writer
                elif target == self.base + 0x3a930:
                    # Reviewed std::string(data,length) helper: writes size/capacity
                    # at +0x10/+0x18 and copies RDX bytes with length R8 to RCX.
                    memory[writer] = argument
                    result = writer
                elif isinstance(target, int) and target - self.base in self.method_at:
                    owner, name = self.method_at[target - self.base]
                    if name == 'getSaveString': base_calls.append({'class': owner, 'rva': hex(rva), 'callee_rva': hex(target - self.base)})
                    result = ('call_result', owner, name, writer, argument)
                else: result = ('call_result', hex(target - self.base) if isinstance(target, int) else repr(target), writer, argument)
                for register in ['rax', 'rcx', 'rdx', 'r8', 'r9', 'r10', 'r11', 'xmm0', 'xmm1', 'xmm2', 'xmm3', 'xmm4', 'xmm5']: regs[register] = None
                regs['rax'] = result
            elif ops and ops[0].type == X86_OP_REG and mnemonic not in {'nop', 'jmp', 'ret', 'int3'} and not mnemonic.startswith('j'):
                # Unknown arithmetic must not leave a stale constant usable as a key.
                write(ops[0], ('operation', mnemonic, read(ops[0]), *(read(op) for op in ops[1:])))

        by_address = {instruction.address: instruction for instruction in instructions}

        def next_values(comma, writer):
            """Follow real control flow through tail-merged numeric insertions.

            MSVC shares the final float insertion block between different keys.
            Address-order matching misses these writes and gives their fields to
            whichever key appears last. Each comma site gets its own value flow.
            """
            call = by_address[self.base + int(comma['rva'], 16)]
            saved_regs, saved_memory = snapshots[int(comma['rva'], 16)]
            initial = dict(saved_regs)
            for n in ['rax', 'rcx', 'rdx', 'r8', 'r9', 'r10', 'r11', 'xmm0', 'xmm1', 'xmm2', 'xmm3', 'xmm4', 'xmm5']: initial[n] = None
            queue = [(call.address + call.size, initial, dict(saved_memory), set())]
            found = []
            iterations = 0
            while queue and iterations < 500:
                pc, vr, vm, visited = queue.pop()
                while pc in by_address and pc not in visited and iterations < 500:
                    iterations += 1
                    visited = visited | {pc}
                    ins = by_address[pc]
                    rops, name = ins.operands, ins.mnemonic
                    rname = lambda number: alias(ins.reg_name(number))
                    def at(op):
                        if op.type != X86_OP_MEM: return None
                        m = op.mem
                        b = ins.address + ins.size if m.base and rname(m.base) == 'rip' else vr.get(rname(m.base)) if m.base else 0
                        idx = vr.get(rname(m.index)) if m.index else 0
                        return add(b, m.disp + idx * m.scale) if isinstance(idx, int) else None
                    def get(op):
                        if op.type == X86_OP_REG: return vr.get(rname(op.reg))
                        if op.type == X86_OP_IMM: return op.imm
                        a = at(op)
                        if isinstance(a, tuple) and a[:2] == ('address', 'this'): return ('field', a[2], op.size, ins.address - self.base)
                        if a in vm: return vm[a]
                        if isinstance(a, int) and 0 <= a - self.base <= len(self.image) - op.size: return int.from_bytes(self.image[a-self.base:a-self.base+op.size], 'little')
                        return ('dereference', a, op.size, ins.address - self.base) if a is not None else None
                    def put(op, v):
                        if op.type == X86_OP_REG: vr[rname(op.reg)] = v
                        elif op.type == X86_OP_MEM:
                            a = at(op)
                            if a is not None: vm[a] = v
                    if name == 'jmp' and rops[0].type == X86_OP_IMM:
                        pc = rops[0].imm
                        continue
                    if name.startswith('j') and rops[0].type == X86_OP_IMM:
                        queue.append((rops[0].imm, dict(vr), dict(vm), set(visited)))
                    elif name == 'ret': break
                    elif name in {'mov', 'movzx', 'movsx', 'movsxd', 'movss', 'movsd', 'movaps', 'movups', 'movdqa', 'movdqu', 'movd', 'movq'} and len(rops) == 2: put(rops[0], get(rops[1]))
                    elif name == 'lea' and len(rops) == 2: put(rops[0], at(rops[1]))
                    elif name.startswith(('cvt', 'vcvt')) and len(rops) >= 2: put(rops[0], ('conversion', name, get(rops[-1])))
                    elif name in {'xor', 'xorps', 'pxor'} and len(rops) == 2 and rops[0].type == rops[1].type == X86_OP_REG and rname(rops[0].reg) == rname(rops[1].reg): put(rops[0], 0)
                    elif name in {'add', 'sub'} and len(rops) == 2:
                        v = get(rops[1]); put(rops[0], add(get(rops[0]), v if name == 'add' else -v) if isinstance(v, int) else None)
                    elif name == 'call':
                        target = at(rops[0]) if rops[0].type == X86_OP_MEM else get(rops[0])
                        imported = self.imports.get(target-self.base) if isinstance(target, int) else None
                        destination, argument = vr.get('rcx'), vr.get('rdx')
                        result = None
                        if imported and imported.startswith('??6') and 'BasicWriter' in imported:
                            kind = 'string' if 'BasicStringRef' in imported else 'real' if imported.endswith('N@Z') else 'int'
                            if kind == 'real': argument = vr.get('xmm1')
                            elif kind == 'string': argument = vm.get(argument, argument)
                            literal = self.literal(argument) if kind == 'string' else None
                            if repr(destination) == writer and literal != ',':
                                found.append({'rva': hex(ins.address-self.base), 'kind': kind, 'writer': writer, 'value': argument, 'literal': literal})
                            # Another comma terminates this pending value region.
                            break
                        if imported and imported.startswith('??0') and 'BasicStringRef' in imported:
                            vm[destination] = vm.get(argument, argument); result = destination
                        elif imported and 'BasicWriter' in imported and 'c_str' in imported:
                            result = ('writer_text', repr(destination))
                        elif target == self.base + 0x3a930:
                            vm[destination] = argument; result = destination
                        else: result = ('call_result', imported or (hex(target-self.base) if isinstance(target,int) else repr(target)), destination, argument)
                        for n in ['rax', 'rcx', 'rdx', 'r8', 'r9', 'r10', 'r11', 'xmm0', 'xmm1', 'xmm2', 'xmm3', 'xmm4', 'xmm5']: vr[n] = None
                        vr['rax'] = result
                    elif rops and rops[0].type == X86_OP_REG and name not in {'nop', 'cmp', 'test', 'ucomiss', 'comiss', 'ucomisd', 'comisd'} and not name.startswith('j'):
                        put(rops[0], ('operation', name, get(rops[0]), *(get(op) for op in rops[1:])))
                    pc += ins.size
            return list({(v['rva'],repr(v['value'])):v for v in found}.values())

        verified, consumed_values, rejected = [], set(), []
        writers = sorted(set(event['writer'] for event in events))
        for writer in writers:
            stream = [event for event in events if event['writer'] == writer]
            for index, event in enumerate(stream):
                if event['rva'] in consumed_values: continue
                literal = event['literal']
                if event['kind'] == 'string' and literal and re.fullmatch(r',\d+,[^,]*', literal):
                    tokens = literal.split(',')
                    verified.append({'key': int(tokens[1]), 'key_call_rva': event['rva'], 'value_call_rvas': [event['rva']], 'field_loads': [],
                                     'value_type': 'literal', 'literal_value': tokens[2], 'confidence': 'confirmed', 'basis': 'literal comma-key-comma-value inserted into BasicWriter'})
                    continue
                header_key = event['kind'] == 'string' and literal is not None and re.fullmatch(r'k[A-Z]\d+', literal)
                if not header_key and (event['kind'] != 'int' or not isinstance(event['value'], int)): continue
                key = literal if header_key else event['value']
                prior_comma = index > 0 and stream[index - 1]['literal'] == ','
                initial_key = index == 0 and writer in constructors and (key == 1 or header_key)
                following_comma = index + 1 < len(stream) and stream[index + 1]['literal'] == ','
                if not ((prior_comma or initial_key) and following_comma):
                    rejected.append({'value': key, 'rva': event['rva'], 'reason': 'not a comma-delimited key/value insertion'})
                    continue
                values = []
                for candidate in stream[index + 2:]:
                    if candidate['literal'] == ',': break
                    values.append(candidate)
                linear_values = values
                values = next_values(stream[index + 1], writer)
                if not values:
                    rejected.append({'value': key, 'rva': event['rva'], 'reason': 'no actual value insertion following key delimiter'})
                    continue
                # Consume both alternatives of integer/real output branches and
                # every integer in structured-value loops, so values cannot be keys.
                consumed_values.update(value['rva'] for value in values)
                consumed_values.update(value['rva'] for value in linear_values)
                value_writers = sorted({nested for value in values for nested in nested_writers(value['value'])})
                consumed_values.update(value['rva'] for value in events if value['writer'] in value_writers)
                loads = [field for value in values for field in fields(value['value'])]
                verified.append({'key': key, 'key_call_rva': event['rva'], 'leading_comma_rva': stream[index - 1]['rva'] if prior_comma else None,
                                 'value_comma_rva': stream[index + 1]['rva'], 'value_call_rvas': [value['rva'] for value in values],
                                 'field_loads': list({json.dumps(load, sort_keys=True): load for load in loads}.values()),
                                 'nested_value_writers': value_writers, 'value_provenance': [value['value'] for value in values],
                                 'value_type': 'structured' if len(values) > 2 else values[0]['kind'],
                                 'constant_values': [value['value'] for value in values if isinstance(value['value'], int)],
                                 'guard': event['guard'], 'confidence': 'confirmed',
                                 'basis': 'actual comma/key/comma/value BasicWriter insertion sequence with argument provenance'})
        parsed = self.evidence['class_property_access'][cls]['methods'].get('customObjectSetup', {})
        candidates = parsed.get('property_field_store_candidates', {})
        confirmed_fields = []
        def annotated_fields(owner, key, visited=None):
            visited = set() if visited is None else visited
            if owner in visited: return []
            visited.add(owner)
            definition = self.broma['classes'].get(owner, {})
            own = [{'class': owner, 'field': prop['field'], 'cpp_type': prop['cpp_type'], 'line': prop['line']}
                   for prop in definition.get('properties', []) if prop['key'] == key]
            return own + [field for parent in definition.get('bases', []) for field in annotated_fields(parent, key, visited)]
        for item in verified:
            for load in item['field_loads']:
                if load['field_offset'] == '0x0': continue  # Receiver "this" is not a member.
                stores = [store for store in candidates.get(str(item['key']), []) if store['field_offset'] == load['field_offset']]
                annotations = annotated_fields(cls, item['key'])
                confirmed_fields.append({'key': item['key'], 'field_offset': load['field_offset'], 'width': load['width'],
                                         'serializer_key_rva': item['key_call_rva'], 'serializer_load_rva': load['load_rva'],
                                         'parser_store_rvas': [store['rva'] for store in stores],
                                         'broma_fields': annotations,
                                         'value_writer_type': item['value_type'], 'confidence': 'confirmed',
                                         'basis': 'member value provenance reaches the verified property value writer' + ('; matching parser member store' if stores else '')})
        key_calls = {item['key_call_rva'] for item in verified}
        unclassified = [{k:v for k,v in event.items() if k in {'rva','kind','literal','import_rva','value'}}
                        for event in events if event['rva'] not in key_calls | consumed_values and event['literal'] != ',']
        inherited_insertions = [{**event, 'base_class': base_serializer(event['value']), 'confidence': 'confirmed',
                                 'basis': 'BasicStringRef constructed from the return value of a Broma-bound base getSaveString call'}
                                for event in unclassified if event['kind'] == 'string' and base_serializer(event['value'])]
        unclassified = [event for event in unclassified if not (event['kind'] == 'string' and base_serializer(event['value']))]
        unclassified_numeric = [event for event in unclassified if event['kind'] != 'string']
        complete = len(unclassified) == 0 and len(rejected) == 0
        return {'rva': method['rva'], 'end_rva': method['end_rva'], 'direct_write_set': sorted({item['key'] for item in verified if isinstance(item['key'], int)}),
                'header_write_set': sorted({item['key'] for item in verified if isinstance(item['key'], str)}),
                'verified_writes': verified, 'verified_property_fields': confirmed_fields, 'base_serializer_calls': base_calls,
                'rejected_constant_values': rejected, 'writer_insertions': len(events),
                'inherited_string_insertions': inherited_insertions,
                'unclassified_insertions': unclassified, 'unclassified_numeric_insertions': len(unclassified_numeric),
                'complete_static_numeric_key_classification': len(unclassified_numeric) == 0 and len(rejected) == 0,
                'complete': complete, 'schema_complete': False,
                'scope': 'All imported BasicWriter insertions in this PE-bounded getSaveString method are classified as static keys, values, nested value formatting, delimiters, or inherited serialization.',
                'limitations': 'Extraction completeness does not mean every factory ID assigned to this class supports every key in its class-wide union. Conditional object-ID branches and schema semantics require separate evidence. Header string keys are reported separately. Raw future properties remain lossless.'}

    def run(self):
        result = {'format': 'gmdtool-verified-serializer-writes-v1', 'game_version': '2.2081',
                  'executable_sha256': hashlib.sha256(self.blob).hexdigest(), 'classes': {}}
        result['reviewed_helpers'] = [{'rva': '0x3a930', 'operation': 'std::string construction from RDX bytes and R8 length into RCX',
                                       'evidence': ['0x3a961: mov qword ptr [rcx + 0x18], 0xf', '0x3a96f: mov qword ptr [rcx + 0x10], r8',
                                                    '0x3a973: call 0x1404d1830 (copy bytes)', '0x3a9ad: mov rdx, r14 (saved input bytes)',
                                                    '0x3a9b0: mov qword ptr [rsi + 0x10], rdi (saved length)', '0x3a9b7: mov qword ptr [rsi + 0x18], rbp (capacity)']}]
        for cls, info in self.evidence['class_property_access'].items():
            method = info['methods'].get('getSaveString')
            if method and 'end_rva' in method: result['classes'][cls] = self.analyze(cls, method)
        def inherited(cls, visited=None):
            visited = set() if visited is None else visited
            if cls in visited: return set()
            visited.add(cls)
            own = result['classes'].get(cls, {})
            keys = set(own.get('direct_write_set', []))
            for call in own.get('base_serializer_calls', []): keys.update(inherited(call['class'], visited))
            return keys
        for cls, item in result['classes'].items(): item['effective_write_set'] = sorted(inherited(cls))
        result['statistics'] = {'classes': len(result['classes']), 'complete_classifications': sum(item['complete'] for item in result['classes'].values()),
                                'verified_direct_key_writes': sum(isinstance(w['key'],int) for item in result['classes'].values() for w in item['verified_writes']),
                                'verified_header_key_writes': sum(isinstance(w['key'],str) for item in result['classes'].values() for w in item['verified_writes']),
                                'verified_property_fields': sum(len(item['verified_property_fields']) for item in result['classes'].values()),
                                'unique_keys': len({key for item in result['classes'].values() for key in item['direct_write_set']})}
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    parser.add_argument('--evidence', type=Path, default=Path('tools/reverse/evidence/executable-2.2081.json'))
    parser.add_argument('--broma', type=Path, default=Path('tools/reverse/evidence/broma-2.2081.json'))
    parser.add_argument('--out', type=Path, default=Path('tools/reverse/evidence/write-sets-2.2081.json'))
    args = parser.parse_args()
    analysis = Analyzer(args.executable, json.loads(args.evidence.read_text(encoding='utf-8')), json.loads(args.broma.read_text(encoding='utf-8'))).run()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(analysis, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(analysis['statistics']))


if __name__ == '__main__': main()
