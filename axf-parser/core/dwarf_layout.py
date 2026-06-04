"""Parse an AXF's DWARF debug info into a flat type registry + global variable
addresses. Done ONCE per firmware build (DWARF parsing is slow); the result is
cached as layout.json and reused for every dump.

Public API:
    parse_dwarf(dwarf) -> {"types": {...}, "variables": {...}}
"""
import struct

from elftools.elf.elffile import ELFFile


def _uleb128(data, index=0):
    result, shift = 0, 0
    while index < len(data):
        b = data[index]
        index += 1
        result |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            break
        shift += 7
    return result


def _member_offset(attr):
    if not attr:
        return 0
    loc = attr.value
    if isinstance(loc, int):
        return loc
    if isinstance(loc, (list, tuple, bytes, bytearray)) and loc and loc[0] == 0x23:
        return _uleb128(bytes(loc), 1)
    return 0


def _type_die(die):
    return die.get_DIE_from_attribute('DW_AT_type') if 'DW_AT_type' in die.attributes else None


def parse_dwarf(dwarf):
    """Flatten the DWARF graph into {types, variables}.

    types:     {type_id(str): {tag, ...}}  keyed by DIE offset
    variables: {name(str): {address:int, type_id:str}} for DW_OP_addr globals
    """
    types = {}

    def process_type(die):
        if not die:
            return None
        tid = str(die.offset)
        if tid in types:
            return tid
        types[tid] = {"tag": "processing"}   # guard against cycles
        tag = die.tag

        if tag in ('DW_TAG_typedef', 'DW_TAG_const_type', 'DW_TAG_volatile_type'):
            node = {"tag": "alias", "target_id": process_type(_type_die(die))}
            if tag == 'DW_TAG_typedef' and 'DW_AT_name' in die.attributes:
                node["name"] = die.attributes['DW_AT_name'].value.decode()
            types[tid] = node

        elif tag == 'DW_TAG_base_type':
            a = die.attributes
            types[tid] = {
                "tag": "base",
                "name": a['DW_AT_name'].value.decode() if 'DW_AT_name' in a else "unknown",
                "size": a['DW_AT_byte_size'].value if 'DW_AT_byte_size' in a else 0,
                "encoding": a['DW_AT_encoding'].value if 'DW_AT_encoding' in a else 0,
            }

        elif tag == 'DW_TAG_pointer_type':
            a = die.attributes
            tgt = _type_die(die)
            types[tid] = {
                "tag": "pointer",
                "size": a['DW_AT_byte_size'].value if 'DW_AT_byte_size' in a else 4,
                "target_id": process_type(tgt) if tgt else None,
            }

        elif tag in ('DW_TAG_structure_type', 'DW_TAG_union_type', 'DW_TAG_class_type'):
            is_union = tag == 'DW_TAG_union_type'
            size = die.attributes['DW_AT_byte_size'].value if 'DW_AT_byte_size' in die.attributes else 0
            members, anon = {}, 0
            for child in die.iter_children():
                if child.tag not in ('DW_TAG_member', 'DW_TAG_inheritance'):
                    continue
                if 'DW_AT_name' in child.attributes:
                    mname = child.attributes['DW_AT_name'].value.decode()
                else:
                    mname = f"__anon_{anon}"
                    anon += 1
                m = {
                    "offset": 0 if is_union else _member_offset(child.attributes.get('DW_AT_data_member_location')),
                    "type_id": process_type(_type_die(child)),
                }
                if 'DW_AT_bit_size' in child.attributes:
                    m['bit_size'] = child.attributes['DW_AT_bit_size'].value
                    if 'DW_AT_data_bit_offset' in child.attributes:
                        m['data_bit_offset'] = child.attributes['DW_AT_data_bit_offset'].value
                    elif 'DW_AT_bit_offset' in child.attributes:
                        m['bit_offset'] = child.attributes['DW_AT_bit_offset'].value
                members[mname] = m
            node = {"tag": "union" if is_union else "struct", "size": size, "members": members}
            if 'DW_AT_name' in die.attributes:
                node["name"] = die.attributes['DW_AT_name'].value.decode()
            types[tid] = node

        elif tag == 'DW_TAG_array_type':
            elem = process_type(_type_die(die))
            dims = []
            for child in die.iter_children():
                if child.tag != 'DW_TAG_subrange_type':
                    continue
                if 'DW_AT_count' in child.attributes:
                    dims.append(child.attributes['DW_AT_count'].value)
                elif 'DW_AT_upper_bound' in child.attributes:
                    dims.append(child.attributes['DW_AT_upper_bound'].value + 1)
                else:
                    dims.append(0)
            types[tid] = {"tag": "array", "element_type_id": elem, "dimensions": dims or [0]}

        elif tag == 'DW_TAG_enumeration_type':
            size = die.attributes['DW_AT_byte_size'].value if 'DW_AT_byte_size' in die.attributes else 4
            enums = {c.attributes['DW_AT_const_value'].value: c.attributes['DW_AT_name'].value.decode()
                     for c in die.iter_children() if c.tag == 'DW_TAG_enumerator'}
            node = {"tag": "enum", "size": size, "enumerators": enums}
            if 'DW_AT_name' in die.attributes:
                node["name"] = die.attributes['DW_AT_name'].value.decode()
            types[tid] = node

        else:
            types[tid] = {"tag": "unknown", "size": 0}
        return tid

    variables = {}
    for cu in dwarf.iter_CUs():
        for die in cu.iter_DIEs():
            if die.tag != 'DW_TAG_variable':
                continue
            a = die.attributes
            if 'DW_AT_name' not in a or 'DW_AT_location' not in a:
                continue
            if 'DW_AT_declaration' in a:                 # skip extern declarations
                continue
            loc = a['DW_AT_location'].value
            if not isinstance(loc, (list, tuple, bytes, bytearray)) or not loc or loc[0] != 0x03:
                continue                                  # only DW_OP_addr globals
            if len(loc) == 5:
                addr = struct.unpack('<I', bytes(loc[1:]))[0]
            elif len(loc) == 9:
                addr = struct.unpack('<Q', bytes(loc[1:]))[0]
            else:
                continue
            if addr == 0:
                continue
            name = a['DW_AT_name'].value.decode()
            variables[name] = {"address": addr, "type_id": process_type(_type_die(die))}

    return {"types": types, "variables": variables}


def open_axf(path):
    """Return (elf, dwarf) for an AXF path. Caller keeps the file handle open
    via the ELFFile (pyelftools reads lazily)."""
    f = open(path, 'rb')
    elf = ELFFile(f)
    return elf, elf.get_dwarf_info()
