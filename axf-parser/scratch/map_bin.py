
#!/usr/bin/env python3
import json
import struct
import sys

ENDIAN = '<'

def get_type_size(type_id, types_reg):
    """Recursively calculates sizes for aliases and arrays"""
    if not type_id or type_id not in types_reg: 
        return 0
    t = types_reg[type_id]
    
    if t['tag'] == 'alias': 
        return get_type_size(t.get('target_id'), types_reg)
    if t['tag'] == 'array':
        elem_size = get_type_size(t.get('element_type_id'), types_reg)
        count = 1
        for d in t.get('dimensions', []):
            count *= d
        return count * elem_size
    return t.get('size', 0)

def read_multidim_array(elem_tid, dimensions, data_bytes, offset, ctx):
    if not dimensions:
        return decode_memory(elem_tid, data_bytes, offset, ctx)
    
    count = dimensions[0]
    sub_dims = dimensions[1:]
    elem_size = get_type_size(elem_tid, ctx['types'])
    for d in sub_dims: 
        elem_size *= d
    
    return [read_multidim_array(elem_tid, sub_dims, data_bytes, offset + (i * elem_size), ctx) for i in range(count)]

def decode_memory(type_id, data_bytes, offset, ctx, ptr_history=None):
    if ptr_history is None: 
        ptr_history = set()
    if not type_id or type_id not in ctx['types'] or offset >= len(data_bytes) or offset < 0: 
        return None
    
    layout = ctx['types'][type_id]
    tag = layout['tag']
    
    if tag == 'alias':
        return decode_memory(layout.get('target_id'), data_bytes, offset, ctx, ptr_history)

    size = get_type_size(type_id, ctx['types'])
    
    # Base Types
    if tag == 'base':
        enc = layout.get('encoding', 0)
        chunk = data_bytes[offset:offset+size]
        if len(chunk) < size: 
            return chunk.hex()
        
        if size == 4 and enc == 4: 
            fmt = 'f'
        elif size == 8 and enc == 4: 
            fmt = 'd'
        elif size == 1: 
            fmt = '?' if enc == 2 else ('b' if enc == 5 else 'B')
        elif size == 2: 
            fmt = 'h' if enc == 5 else 'H'
        elif size == 4: 
            fmt = 'i' if enc == 5 else 'I'
        elif size == 8: 
            fmt = 'q' if enc == 5 else 'Q'
        else: 
            return chunk.hex()
        try: 
            return struct.unpack(ENDIAN + fmt, chunk)[0]
        except Exception: 
            return chunk.hex()

    # Pointers
    elif tag == 'pointer':
        chunk = data_bytes[offset:offset+size]
        if len(chunk) < size: 
            return chunk.hex()
        addr = struct.unpack(ENDIAN + ('I' if size == 4 else 'Q'), chunk)[0]
        addr_str = f"0x{addr:08x}"
        
        target_tid = layout.get('target_id')
        if addr != 0 and ctx['bin_base'] <= addr < (ctx['bin_base'] + len(ctx['full_dump'])) and target_tid and addr not in ptr_history:
            ptr_history.add(addr)
            deref_offset = addr - ctx['bin_base']
            deref_data = decode_memory(target_tid, ctx['full_dump'], deref_offset, ctx, ptr_history)
            ptr_history.remove(addr)
            return {"@address": addr_str, "->": deref_data}
        return addr_str

    # Arrays
    elif tag == 'array':
        return read_multidim_array(layout.get('element_type_id'), layout.get('dimensions', []), data_bytes, offset, ctx)

    # Structs & Unions
    elif tag in ('struct', 'union'):
        result = {}
        for m_name, m_data in layout.get('members', {}).items():
            m_offset = offset + m_data.get('offset', 0)
            
            # Check for bitfields inside member data
            if 'bit_size' in m_data:
                m_size = get_type_size(m_data.get('type_id'), ctx['types']) or 4
                chunk = data_bytes[m_offset:m_offset+m_size]
                if len(chunk) == m_size:
                    raw_val = struct.unpack(ENDIAN + ('I' if m_size == 4 else ('B' if m_size == 1 else ('H' if m_size == 2 else 'Q'))), chunk)[0]
                    bit_size = m_data['bit_size']
                    if 'data_bit_offset' in m_data:
                        val = (raw_val >> m_data['data_bit_offset']) & ((1 << bit_size) - 1)
                        result[m_name] = val
                        continue
                    elif 'bit_offset' in m_data:
                        shift = (m_size * 8) - m_data['bit_offset'] - bit_size
                        val = (raw_val >> shift) & ((1 << bit_size) - 1)
                        result[m_name] = val
                        continue

            result[m_name] = decode_memory(m_data.get('type_id'), data_bytes, m_offset, ctx, ptr_history)
        return result

    # Enums
    elif tag == 'enum':
        chunk = data_bytes[offset:offset+size]
        if len(chunk) < size: 
            return chunk.hex()
        val = struct.unpack(ENDIAN + ('I' if size == 4 else 'B'), chunk)[0]
        return layout.get('enumerators', {}).get(str(val), val)

    return data_bytes[offset:offset+size].hex() if size > 0 else None

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python 2_map_binary.py <layout.json> <dump.bin> <symbol_name>")
        sys.exit(1)

    with open(sys.argv[1], 'r') as f:
        layout_db = json.load(f)
        
    symbol_name = sys.argv[3]
    if symbol_name not in layout_db['variables']:
        print(f"Error: Symbol '{symbol_name}' not found in layout database.")
        sys.exit(1)
        
    var_info = layout_db['variables'][symbol_name]
    bin_base = 0x20000000 
    
    with open(sys.argv[2], 'rb') as f:
        full_dump = f.read()

    offset = var_info['address'] - bin_base
    if offset < 0 or offset > len(full_dump):
        print(f"Symbol address {hex(var_info['address'])} is outside binary dump base {hex(bin_base)}.")
        sys.exit(1)

    ctx = {
        'types': layout_db['types'],
        'full_dump': full_dump,
        'bin_base': bin_base
    }

    result = decode_memory(var_info['type_id'], full_dump, offset, ctx)

    out_file = f'{symbol_name}_data.json'
    with open(out_file, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"✓ Extracted data saved to {out_file}")

