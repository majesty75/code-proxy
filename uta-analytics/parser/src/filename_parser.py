import re
from datetime import datetime

# Strict naming convention. Renames vs. previous schema:
#   "platform"        → "controller"     (SIRIUS is the controller chip)
#   "production_step" → "patch_version"  (P09 is a patch level)
FILENAME_RE = re.compile(
    r"^(?P<slot_id>R\d+S\d+-\d+)_"
    r"(?P<date>\d{8})_(?P<time>\d{6})_"
    r"(?P<exec_type>[A-Z]+)_"
    r"(?P<project>[A-Z0-9]+)_"
    r"(?P<controller>[A-Z]+)_"
    r"(?P<interface>(?:UFS|eMMC)[_\d]+)_"
    r"(?P<fw_arch>V\d+)_"
    r"(?P<nand_type>[A-Za-z]+)_"
    r"(?P<nand_density>\d+[A-Za-z]+)_"
    r"(?P<manufacturer>[A-Za-z0-9]+)_"
    r"(?P<package_density>\d+[A-Za-z]+)_"
    r"(?P<patch_version>P\d+)_"
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
    Parse a UTA log filename into structured metadata.

    Returns a dict with keys matching uta.test_sessions columns. Falls back
    to a relaxed best-effort parse when the strict pattern doesn't match —
    callers always get whatever fields could be salvaged.
    """
    result: dict = {"log_filename": filename}
    clean_name = filename.replace(".log", "")

    m = FILENAME_RE.match(clean_name)
    if m:
        d = m.groupdict()
        result.update({
            "slot_id": d.get("slot_id", ""),
            "execution_type": d.get("exec_type", ""),
            "project": d.get("project", ""),
            "controller": d.get("controller", ""),
            "interface": d.get("interface", ""),
            "fw_arch": d.get("fw_arch", ""),
            "nand_type": d.get("nand_type", ""),
            "nand_density": d.get("nand_density", ""),
            "manufacturer": d.get("manufacturer", ""),
            "package_density": d.get("package_density", ""),
            "patch_version": d.get("patch_version", ""),
            "release_candidate": d.get("release_candidate", ""),
            "firmware_version": d.get("firmware", ""),
            "engineers": [e for e in d.get("engineers", "").split("_") if e],
            "test_purpose": d.get("test_purpose", ""),
            "storage_type": d.get("storage_type", ""),
        })
        try:
            result["started_at"] = datetime.strptime(
                f"{d['date']}_{d['time']}", "%Y%m%d_%H%M%S"
            )
        except ValueError:
            pass
    else:
        # Relaxed: extract whatever known patterns appear anywhere.
        slot_m = re.search(r"(R\d+S\d+-\d+)", clean_name)
        if slot_m:
            result["slot_id"] = slot_m.group(1)

        dt_m = re.search(r"(\d{8})_(\d{6})", clean_name)
        if dt_m:
            try:
                result["started_at"] = datetime.strptime(
                    f"{dt_m.group(1)}_{dt_m.group(2)}", "%Y%m%d_%H%M%S"
                )
            except ValueError:
                pass

        for field, pat in (
            ("fw_arch",          r"_(V\d+)_"),
            ("patch_version",    r"_(P\d+)_"),
            ("release_candidate", r"_(RC\d+)_"),
            ("firmware_version", r"_(FW\d+)_"),
        ):
            mm = re.search(pat, clean_name)
            if mm:
                result[field] = mm.group(1)

        if "_UFS_" in clean_name or clean_name.endswith("_UFS"):
            result["storage_type"] = "UFS"
        elif "_eMMC_" in clean_name or clean_name.endswith("_eMMC"):
            result["storage_type"] = "eMMC"

    # Decompose slot_id into rack/shelf/slot ints.
    slot_id = result.get("slot_id", "")
    if slot_id:
        sm = re.match(r"R(\d+)S(\d+)-(\d+)", slot_id)
        if sm:
            result["rack"] = int(sm.group(1))
            result["shelf"] = int(sm.group(2))
            result["slot"] = int(sm.group(3))

    return result
