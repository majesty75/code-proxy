"""Read-only lookup of the runtime facts UTA owns: TR name, firmware name, and
the test start time (the relative-time anchor). The AXF identity comes from the
server's own registry; only these per-board runtime values come from UTA.

Opens the SQLite read-only + immutable so it never locks the live DB.
"""
import sqlite3


class UtaLookup:
    def __init__(self, sqlite_path):
        self.path = sqlite_path

    def get(self, boardname):
        """Return (facts, error) where facts = {trname, fw_name, test_started_at}
        and error is None or a reason string."""
        if not self.path:
            return None, "no UTA SQLite configured"
        try:
            uri = f"file:{self.path}?mode=ro&immutable=1"
            con = sqlite3.connect(uri, uri=True, timeout=2.0)
            try:
                row = con.execute(
                    "SELECT trname, fwname, start FROM app_board WHERE boardname=?",
                    (boardname,),
                ).fetchone()
            finally:
                con.close()
        except sqlite3.Error as e:
            return None, f"sqlite error: {e}"
        if not row:
            return None, f"board {boardname} not found"
        trname, fwname, start = row
        if not trname or not fwname:
            return None, "trname/fwname empty in UTA"
        return {"trname": trname, "fw_name": fwname, "test_started_at": start}, None
