from typing import Any
from .base import BaseParser


class UfsQualParser(BaseParser):
    """
    Specialised extractor for UFS-Qual specific perf lines such as:
      Sequential Read IOPS: 120000
      Sequential Write IOPS: 95000

    Only claims a line when it actually contains an IOPS metric to avoid
    swallowing every line of a Qual_UFS file.
    """
    parser_id = "ufs_qual"
    priority = 40

    def can_parse(self, line: str, filename: str) -> bool:
        return "Qual_UFS" in filename and "IOPS" in line

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        result: dict[str, Any] = {"event": "ufs_qual_iops"}
        # Example: "Sequential Read IOPS: 120000"
        if ":" in line:
            metric, _, value = line.partition(":")
            result["metric"] = metric.strip()
            value = value.strip()
            result["raw_value"] = value
            try:
                result["value"] = int(value)
            except ValueError:
                pass
        return result
