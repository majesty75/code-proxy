import re
from datetime import datetime

# Pattern matching the strict log naming convention
FILENAME_RE = re.compile(
    r"^(?P<slot_id>R\d+S\d+-\d+)_"
    r"(?P<date>\d{8})_(?P<time>\d{6})_"
    r"(?P<exec_type>[A-Z]+)_"
    r"(?P<project>[A-Z0-9]+)_"
    r"(?P<platform>[A-Z]+)_"
    r"(?P<interface>(?:UFS|eMMC)[_\d]+)_"
    r"(?P<fw_arch>V\d+)_"
    r"(?P<nand_type>[A-Za-z]+)_"
    r"(?P<nand_density>\d+[A-Za-z]+)_"
    r"(?P<manufacturer>[A-Za-z0-9]+)_"
    r"(?P<package_density>\d+[A-Za-z]+)_"
    r"(?P<prod_step>P\d+)_"
    r"(?P<release_candidate>RC\d+)_"
    r"(?P<firmware>FW\d+)_"
    r"(?P<rack>Rack\d+)_"
    r"(?P<engineers>.+?)_"
    r"(?P<test_purpose>[A-Za-z]+)_"
    r"(?P<storage_type>(?:UFS|eMMC|SSD))"
    r"(?:\.log)?$"
)

def parse_filename(filename: str) -> dict:
    """
    Parse log filename into structured metadata.
    Returns dict with keys matching ClickHouse test_sessions columns.
    Returns partial dict if regex doesn't fully match (graceful degradation).
    """
    result = {"log_filename": filename}
    clean_name = filename.replace(".log", "")

    m = FILENAME_RE.match(clean_name)
    if m:
        d = m.groupdict()
        result.update({
            "slot_id": d.get("slot_id", ""),
            "execution_type": d.get("exec_type", ""),
            "project": d.get("project", ""),
            "platform": d.get("platform", ""),
            "interface": d.get("interface", ""),
            "fw_arch": d.get("fw_arch", ""),
            "nand_type": d.get("nand_type", ""),
            "nand_density": d.get("nand_density", ""),
            "manufacturer": d.get("manufacturer", ""),
            "package_density": d.get("package_density", ""),
            "production_step": d.get("prod_step", ""),
            "release_candidate": d.get("release_candidate", ""),
            "firmware_version": d.get("firmware", ""),
            "engineers": [e for e in d.get("engineers", "").split("_") if e],
            "test_purpose": d.get("test_purpose", ""),
            "storage_type": d.get("storage_type", ""),
        })
        try:
            result["started_at"] = datetime.strptime(f"{d['date']}_{d['time']}", "%Y%m%d_%H%M%S")
        except ValueError:
            pass
    else:
        # Relaxed parsing: extract known patterns anywhere in the string
        slot_m = re.search(r"(R\d+S\d+-\d+)", clean_name)
        if slot_m:
            result["slot_id"] = slot_m.group(1)
            
        dt_m = re.search(r"(\d{8})_(\d{6})", clean_name)
        if dt_m:
            try:
                result["started_at"] = datetime.strptime(f"{dt_m.group(1)}_{dt_m.group(2)}", "%Y%m%d_%H%M%S")
            except ValueError:
                pass
                
        fw_arch_m = re.search(r"_(V\d+)_", clean_name)
        if fw_arch_m:
            result["fw_arch"] = fw_arch_m.group(1)
            
        prod_m = re.search(r"_(P\d+)_", clean_name)
        if prod_m:
            result["production_step"] = prod_m.group(1)
            
        rc_m = re.search(r"_(RC\d+)_", clean_name)
        if rc_m:
            result["release_candidate"] = rc_m.group(1)
            
        fw_m = re.search(r"_(FW\d+)_", clean_name)
        if fw_m:
            result["firmware_version"] = fw_m.group(1)

        if "_UFS_" in clean_name or clean_name.endswith("_UFS"):
            result["storage_type"] = "UFS"
        elif "_eMMC_" in clean_name or clean_name.endswith("_eMMC"):
            result["storage_type"] = "eMMC"

    # Parse rack/shelf/slot numbers
    if "slot_id" in result and result["slot_id"]:
        slot_m = re.match(r"R(\d+)S(\d+)-(\d+)", result["slot_id"])
        if slot_m:
            result["rack"] = int(slot_m.group(1))
            result["shelf"] = int(slot_m.group(2))
            result["slot"] = int(slot_m.group(3))

    return result

