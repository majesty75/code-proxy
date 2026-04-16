from typing import Any
from .base import BaseParser

class UfsQualParser(BaseParser):
    parser_id = "ufs_qual"

    def can_parse(self, line: str, filename: str) -> bool:
        return "Qual_UFS" in filename

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        # Custom extraction logic here
        if "IOPS" in line:
            # Example: "Sequential Read IOPS: 120000"
            parts = line.split(":")
            if len(parts) == 2:
                result["metric"] = parts[0].strip()
                result["value"] = parts[1].strip()
        return result
