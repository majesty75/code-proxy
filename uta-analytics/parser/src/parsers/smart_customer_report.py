import re
from typing import Any
from .base import BaseParser

class SmartCustomerReportParser(BaseParser):
    priority = 13

    @property
    def parser_id(self) -> str:
        return "smart_customer_report"

    def can_parse(self, line: str, filename: str) -> bool:
        return "SmartCustomerReport" in line

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        result: dict[str, Any] = {"event": "smart_customer_report"}

        # Example lines:
        # 0000:00:58 SmartCustomerReport FirmwareSuccessCount = 0
        # 0000:00:37 SmartCustomerReport SLC EC = Max 1 / Min 0 / Avg 0
        # 0000:00:58 SmartCustomerReport FWExceptionSubCodeBitmap96_127 = 0x0 
        # 0000:00:58 SmartCustomerReport FWExceptionTopLevel = 0x0 (None)
        
        # Match time format if exists (e.g. 0000:00:58)
        time_match = re.match(r'^(\d{4}:\d{2}:\d{2})\s+', line)
        if time_match:
            result["log_time"] = time_match.group(1)
            
        # Match the key-value pair after "SmartCustomerReport"
        match = re.search(r'SmartCustomerReport\s+(.*?)\s*=\s*(.*)', line)
        if match:
            key = match.group(1).strip()
            val_str = match.group(2).strip()
            
            result["report_key"] = key
            result["report_value"] = val_str
            
            # Try to infer types for specific single values
            if val_str.isdigit():
                result["report_value_int"] = int(val_str)
            elif val_str.startswith("0x"):
                try:
                    # Sometimes it has a trailing part like '0x0 (None)'
                    hex_val = val_str.split()[0]
                    result["report_value_int"] = int(hex_val, 16)
                except ValueError:
                    pass
            elif " / " in val_str:
                # Handle things like "Max 1 / Min 0 / Avg 0"
                parts = val_str.split(" / ")
                sub_values = {}
                for part in parts:
                    sub_match = re.match(r'([A-Za-z]+)\s+(\d+)', part.strip())
                    if sub_match:
                        sub_values[sub_match.group(1)] = int(sub_match.group(2))
                if sub_values:
                    result["report_sub_values"] = sub_values
                    
        return result
