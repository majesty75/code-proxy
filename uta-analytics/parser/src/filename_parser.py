import re
from datetime import datetime

# Pattern matching the log naming convention from docs/log-naming.md
FILENAME_RE = re.compile(
    r"^(?P<slot_id>R\d+S\d+-\d+)_"
    r"(?P<date>\d{8})_(?P<time>\d{6})_"
    r"(?P<exec_type>EXEC|RETEST|DEBUG|SMOKE)_"
    r"(?P<project>\w+?)_"
    r"(?P<platform>[A-Z]+)_"
    r"(?P<interface>UFS_\d+_\d+|eMMC_\d+_\d+)_"
    r"(?P<fw_arch>V\d+)_"
    r"(?P<nand_type>\w+?)_"
    r"(?P<nand_density>\d+\w+?)_"
    r"(?P<manufacturer>\w+?)_"
    r"(?P<package_density>\d+\w+?)_"
    r"(?P<prod_step>P\d+)_"
    r"(?P<release_candidate>RC\d+)_"
    r"(?P<firmware>FW\d+)_"
    r"(?P<rack>Rack\d+)_"
    r"(?P<engineers>.+?)_"
    r"(?P<test_purpose>\w+?)_"
    r"(?P<storage_type>\w+)"
    r"(?:\.log)?$"
)


def parse_filename(filename: str) -> dict:
    """
    Parse log filename into structured metadata.
    Returns dict with keys matching ClickHouse test_sessions columns.
    Returns partial dict if regex doesn't fully match (graceful degradation).
    """
    result = {"log_filename": filename}

    m = FILENAME_RE.match(filename)
    if not m:
        # Graceful fallback: extract what we can
        parts = filename.replace(".log", "").split("_")
        if parts:
            result["slot_id"] = parts[0] if parts[0].startswith("R") else ""
        return result

    d = m.groupdict()
    result.update({
        "slot_id": d["slot_id"],
        "started_at": datetime.strptime(f"{d['date']}_{d['time']}", "%Y%m%d_%H%M%S"),
        "execution_type": d["exec_type"],
        "project": d["project"],
        "platform": d["platform"],
        "interface": d["interface"],
        "fw_arch": d["fw_arch"],
        "nand_type": d["nand_type"],
        "nand_density": d["nand_density"],
        "manufacturer": d["manufacturer"],
        "package_density": d["package_density"],
        "production_step": d["prod_step"],
        "release_candidate": d["release_candidate"],
        "firmware_version": d["firmware"],
        "engineers": [e for e in d["engineers"].split("_") if e],
        "test_purpose": d["test_purpose"],
        "storage_type": d["storage_type"],
    })

    # Parse rack/shelf/slot numbers
    slot_m = re.match(r"R(\d+)S(\d+)-(\d+)", d["slot_id"])
    if slot_m:
        result["rack"] = int(slot_m.group(1))
        result["shelf"] = int(slot_m.group(2))
        result["slot"] = int(slot_m.group(3))

    return result
