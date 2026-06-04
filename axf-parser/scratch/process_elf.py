#!/usr/bin/env python3
import json
from pathlib import Path
import sys
import struct
from elftools.elf.elffile import ELFFile

def decode_uleb128(data, index=0):
    result, shift = 0, 0
    while index < len(data):
        b = data[index]
        index += 1
        result |= (b & 0x7f) << shift
        if (b & 0x80) == 0: 
            break
        shift += 7
    return result

def get_member_offset(attr):
    if not attr: 
        return 0
    loc = attr.value
    if isinstance(loc, int): 
        return loc
    if isinstance(loc, (list, tuple, bytes, bytearray)) and len(loc) > 0 and loc[0] == 0x23:
        return decode_uleb128(bytes(loc), 1)
    return 0

def get_type_die(die):
    return die.get_DIE_from_attribute('DW_AT_type') if 'DW_AT_type' in die.attributes else None

def parse_dwarf_types(dwarf):
    """Flattens the DWARF graph into a Type Registry."""
    types_registry = {}
    
    def process_type(die):
        if not die: 
            return None
        tid = str(die.offset)
        if tid in types_registry: 
            return tid # Already processed
        
        types_registry[tid] = {"tag": "processing"} # Prevent circular recursion
        
        tag = die.tag
        if tag in ('DW_TAG_typedef', 'DW_TAG_const_type', 'DW_TAG_volatile_type'):
            t_die = get_type_die(die)
            real_tid = process_type(t_die)
            types_registry[tid] = {"tag": "alias", "target_id": real_tid}
            
        elif tag == 'DW_TAG_base_type':
            name = die.attributes.get('DW_AT_name').value.decode() if 'DW_AT_name' in die.attributes else "unknown"
            size = die.attributes.get('DW_AT_byte_size').value if 'DW_AT_byte_size' in die.attributes else 0
            enc = die.attributes.get('DW_AT_encoding').value if 'DW_AT_encoding' in die.attributes else 0
            types_registry[tid] = {"tag": "base", "name": name, "size": size, "encoding": enc}
            
        elif tag == 'DW_TAG_pointer_type':
            size = die.attributes.get('DW_AT_byte_size').value if 'DW_AT_byte_size' in die.attributes else 4
            target_die = get_type_die(die)
            target_tid = process_type(target_die) if target_die else None
            types_registry[tid] = {"tag": "pointer", "size": size, "target_id": target_tid}
            
        elif tag in ('DW_TAG_structure_type', 'DW_TAG_union_type', 'DW_TAG_class_type'):
            size = die.attributes.get('DW_AT_byte_size').value if 'DW_AT_byte_size' in die.attributes else 0
            is_union = (tag == 'DW_TAG_union_type')
            members = {}
            anon_c = 0
            for child in die.iter_children():
                if child.tag in ('DW_TAG_member', 'DW_TAG_inheritance'):
                    m_name = child.attributes.get('DW_AT_name').value.decode() if 'DW_AT_name' in child.attributes else f"__anon_{anon_c}"
                    if 'DW_AT_name' not in child.attributes: 
                        anon_c += 1
                    
                    m_offset = 0 if is_union else get_member_offset(child.attributes.get('DW_AT_data_member_location'))
                    m_tid = process_type(get_type_die(child))
                    
                    m_data = {"offset": m_offset, "type_id": m_tid}
                    
                    if 'DW_AT_bit_size' in child.attributes:
                        m_data['bit_size'] = child.attributes['DW_AT_bit_size'].value
                        if 'DW_AT_data_bit_offset' in child.attributes: 
                            m_data['data_bit_offset'] = child.attributes['DW_AT_data_bit_offset'].value
                        elif 'DW_AT_bit_offset' in child.attributes: 
                            m_data['bit_offset'] = child.attributes['DW_AT_bit_offset'].value
                    
                    members[m_name] = m_data
            types_registry[tid] = {"tag": "struct" if not is_union else "union", "size": size, "members": members}
            
        elif tag == 'DW_TAG_array_type':
            elem_tid = process_type(get_type_die(die))
            dims = []
            for child in die.iter_children():
                if child.tag == 'DW_TAG_subrange_type':
                    if 'DW_AT_count' in child.attributes: 
                        dims.append(child.attributes['DW_AT_count'].value)
                    elif 'DW_AT_upper_bound' in child.attributes: 
                        dims.append(child.attributes['DW_AT_upper_bound'].value + 1)
                    else: 
                        dims.append(0)
            if not dims: 
                dims = [0]
            
            # Temporary size calculation
            types_registry[tid] = {"tag": "array", "element_type_id": elem_tid, "dimensions": dims}
            
        elif tag == 'DW_TAG_enumeration_type':
            size = die.attributes.get('DW_AT_byte_size').value if 'DW_AT_byte_size' in die.attributes else 4
            enums = {child.attributes['DW_AT_const_value'].value: child.attributes['DW_AT_name'].value.decode() 
                     for child in die.iter_children() if child.tag == 'DW_TAG_enumerator'}
            types_registry[tid] = {"tag": "enum", "size": size, "enumerators": enums}
            
        else:
            types_registry[tid] = {"tag": "unknown", "size": 0}

        return tid

    # Find all global variables and their types
    variables = {}
    for cu in dwarf.iter_CUs():
        for die in cu.iter_DIEs():
            if die.tag == 'DW_TAG_variable' and 'DW_AT_name' in die.attributes and 'DW_AT_location' in die.attributes:
                name = die.attributes['DW_AT_name'].value.decode()
                loc = die.attributes['DW_AT_location'].value
                
                # Check for DW_OP_addr (0x03) followed by 4 or 8 byte address
                if isinstance(loc, list) and len(loc) > 0 and loc[0] == 0x03:
                    # Quick hack to grab the integer address from DWARF location block
                    if len(loc) == 5: 
                        addr = struct.unpack('<I', bytes(loc[1:]))[0]
                    elif len(loc) == 9: 
                        addr = struct.unpack('<Q', bytes(loc[1:]))[0]
                    else: 
                        continue
                    
                    t_die = get_type_die(die)
                    t_id = process_type(t_die)
                    variables[name] = {"address": addr, "type_id": t_id}

    return {"types": types_registry, "variables": variables}

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python parse_elf.py <firmware.axf>")
        sys.exit(1)

    axf = Path(sys.argv[1])
    if not axf.exists():
        print("AXF file not found")

    files = []

    if axf.is_dir():
        for file in axf.glob("*.axf"):
            files.append(file)
    else:        
        files = [axf]

    print("Parsing DWARF (This may take a moment on large ELFs)...")
    for file in files:
        with open(file, 'rb') as f:
            elf = ELFFile(f)
            dwarf = elf.get_dwarf_info()
            print(f"Parsing DWARF from {file}")
            layout = parse_dwarf_types(dwarf)

        output_file = Path(file.parent, "layout", f"{file.stem}.json")
        
        output_file.parent.mkdir(exist_ok=True, parents=True)

        with open(output_file, 'w') as f:
            json.dump(layout, f, indent=2)
        print(f"Saved {file} layout to {output_file}")
