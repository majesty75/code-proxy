---
name: uta-system-reference
description: Complete reference documentation for battle-tested UTA system models and analytics architecture
metadata: 
  node_type: memory
  type: reference
  originSessionId: 2e03c67a-6f46-4b3a-b64b-501e21edaeda
---

# UTA System Reference & Analytics Architecture

## Project Overview

**UTA System:**
- **Location:** `/home/gjayeshbhai/projects/uta`
- **Type:** Django web application for Unified Test Analytics (UTA)
- **Database:** SQLite at `/home/gjayeshbhai/projects/uta/database/sqlite.db`
- **Purpose:** Manages test execution on remote UFS flash hardware boards

**Analytics System:**
- **Location:** `/home/gjayeshbhai/uta-analytics`
- **Purpose:** Real-time visibility into test execution metrics and board health


## Architecture Evolution

### Current (Legacy) Approach - Log Parsing

**Stack:**
- Vector (log tailing) → Kafka → Python Parsers → ClickHouse → Grafana

**Process:**
1. User assigns Test Request (TR) to boards via UTA UI
2. Test script executes on board
3. Logs generated on server with structured filenames
4. Vector tails logs, ships to Kafka
5. Python parsers extract metadata from filenames and log content
6. ClickHouse stores structured data
7. Grafana visualizes test status and metrics

**Problem:** Logs contain minimal reliable data (only TC pass/fail). Filename parsing is error-prone.

---

### New Approach - AXF Binary Parsing

**Philosophy:** Tap into the source of truth — embedded memory content — not log files.

#### Core Concept: TRACE32 + AXF + SRAM Dumps

**TRACE32 (Lauterbach):**
- Hardware debugger for ARM microcontrollers
- Each rack has one TRACE32 instance
- Can attach to any board in the rack
- Executes PRACTICE scripts for automation

**AXF (Absolute eXecutable Format):**
- Executable file format with embedded DWARF debug info
- Contains type definitions, variable addresses, struct layouts
- Each product/core has unique AXF

**SRAM Dumps:**
- TRACE32 PRACTICE scripts dump board SRAM content
- Generates .bin files containing raw memory
- Naming format: `board_core_timestamp.bin`
- Example: `R7S1-01_H_20250603_143522.bin`

---

## New Architecture

### Components

```
┌─────────────────────────────────────────────────────────────────┐
│                    UTA Test Environment                          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │   Rack R7    │    │   Rack R8    │    │   Other...   │       │
│  │  ┌────────┐  │    │  ┌────────┐  │    │              │       │
│  │  │TRACE32 │  │    │  │TRACE32 │  │    │              │       │
│  │  └───┬────┘  │    │  └───┬────┘  │    │              │       │
│  │      │       │    │      │       │    │              │       │
│  │  R7S1-01 H/M │    │  R8S1-01 H/M │    │              │       │
│  │  R7S1-02 H/M │    │  R8S1-02 H/M │    │              │       │
│  │  ... Boards   │    │  ... Boards   │    │              │       │
│  └──────┬────────┘    └──────┬────────┘    └──────────────┘       │
└─────────┼──────────────────┼──────────────────┬───────────────────┘
          │                  │                  │
    DWARF/PRACTICE      DWARF/PRACTICE     DWARF/PRACTICE
    Scripts             Scripts            Scripts
          │                  │                  │
          ▼                  ▼                  ▼
    ┌────────────────────────────────────────────────────┐
    │  SRAM Dump Directory (Per Server)                   │
    │  /uta/dumps/                                        │
    │  R7S1-01_H_20250603_143522.bin                     │
    │  R7S1-01_M_20250603_143523.bin                     │
    │  R7S1-02_H_20250603_143524.bin                     │
    │  ...                                                │
    └──────────────┬─────────────────────────────────────┘
                   │ (watch for new files)
                   ▼
          ┌────────────────┐
          │  File Watcher │  ← Monitors dump directory
          └───────┬────────┘
                  │
         +--------+--------+
         │                 │
         │  File Complete  │ ← Wait for file write to finish
         │  Detection     │
         │                 │
         +--------+--------+
                  │
    ┌─────────────┼─────────────┬────────────────┐
    │             │             │                │
    ▼             ▼             ▼                ▼
┌─────────┐  ┌──────────┐  ┌─────────┐  ┌──────────────┐
│ Stream │  │ Metadata │  │  Lookup │  │ Board → TR   │
│   BIN  │  │ Extractor │  │ Service│  │   Mapping    │
└────┬────┘  └──────────┘  └─────────┘  └──────┬───────┘
     │                                           │
     └─────────────────┬───────────────────────┘
                       │
                       ▼
              ┌─────────────────┐
              │ Analytics Server │
              └─────────┬───────┘
                        │
            ┌───────────┼────────────┬─────────────┐
            │           │            │             │
            ▼           ▼            ▼             ▼
      ┌─────────┐ ┌──────────┐ ┌─────────┐ ┌──────────────┐
      │ AXF     │ │ AXF      │ │ Product │ │   Storage    │
      │ Parser  │ │ Library  │ │ Config  │ │ (ClickHouse) │
      └────┬────┘ └──────────┘ └─────────┘ └──────┬───────┘
           │                                         │
           ▼                                         ▼
      ┌──────────┐                           ┌──────────────┐
      │  JSON    │                           │ TR-Organized │
      │  Output  │                           │   Data       │
      └──────────┘                           └──────────────┘
                                                │
                                                ▼
                                       ┌──────────────────┐
                                       │   Grafana        │
                                       │   Dashboard      │
                                       │   Visualization │
                                       └──────────────────┘
```


## System Architecture (UTA Core)

### Data Flow - Testing

1. **User Issues Test Request:**
   - User assigns TR to boards via UTA UI
   - `app_board.trname` updated for assigned boards

2. **TR → Board Mapping:**
   - Each TR can span multiple racks and shelves
   - **Key:** `app_board.trname` is the primary aggregation key

3. **Test Execution:**
   - Script runs on board via UTA server
   - Multiple test cases execute in sequence
   - Log file generated (minimal reliable data)

4. **Monitoring:**
   - `app_board.status` tracks board state (Testing/Free/Keep/Passed)
   - `app_board.currenttcname` tracks current test case
   - `app_board.progress` tracks overall progress

5. **Firmware Tracking:**
   - `app_board.fwname` stores current firmware
   - `app_fwhistory` logs firmware updates

---

## AXF Parsing Infrastructure

**Location:** `/home/gjayeshbhai/uta-analytics/map_axf/`

### Core Components

| File | Purpose | Key Classes/Functions |
|------|---------|---------------------|
| **process_elf.py** | Parses DWARF from AXF/ELF | `parse_dwarf_types()`, `build_type_layout()` |
| **elf.py** | Generates type registry | `parse_dwarf_types()` |
| **map_bin.py** | Decodes binary dumps | `decode_memory()`, `read_multidim_array()` |
| **trace32_elf.py** | Live TRACE32 debugging | `extract_t32_variable()`, T32 RCL API |
| **observe_ufs.py** | Web UI for diff viewer | FastAPI, timeline diff viewer |
| **compare.py** | Command-line diff tool | Sparse memory comparison |

### DWARF Parsing Architecture

**DWARF (Debugging With Attributed Record Formats):**
- Embedded in AXF/ELF files
- Contains type definitions, variable addresses, struct layouts
- Used by compilers and debuggers

**Type Registry Structure (JSON):**
```json
{
  "types": {
    "offset_1": {
      "tag": "base|pointer|struct|array|enum",
      "size": 4,
      "encoding": 5,
      "name": "int",
      "members": {...},
      "elements": {...}
    }
  },
  "variables": {
    "global_var_name": {
      "address": 0x20000000,
      "type_id": "offset_1"
    }
  }
}
```

**Supported Types:**
- **Base:** int, float, bool, char
- **Pointer:** 32-bit/64-bit with dereferencing
- **Array:** Multi-dimensional with automatic decoding
- **Struct:** Nested member decoding with offsets
- **Union:** Member decoding (shared memory)
- **Enum:** Symbolic name mapping
- **Alias/Typedef:** Type forwarding
- **Bitfields:** Bit-level extraction

### Binary Decoding Process

```
AXF File ──┐
           │→ DWARF Parser → Type Registry (JSON)
           │                                      └── Variable Addresses
           │
Binary Dump ────┘
                  └───→ Memory decoder uses Type Registry
                          └───→ Structured JSON Output
```

**Example Pipeline:**
```bash
# Step 1: Generate layout from AXF
python process_elf.py NCORE0_SIRIUS_V8_TLC.axf
# Output: layout/NCORE0_SIRIUS_V8_TLC.json

# Step 2: Decode binary dump
python map_bin.py layout.json DUMP_H_Core.bin global_variable_name
# Output: global_variable_name_data.json
```

### Complex Structure Support

**Nested Decoding:**
- Pointers automatically dereferenced within dump range
- Circular reference detection
- Array indexing support: `data[0][1].member`

**Bitfields:**
- Support for `DW_AT_bit_size` and `DW_AT_bit_offset`
- Unsigned/signed extraction

**Sparse Memory:**
- Support for non-contiguous memory dumps
- Multiple memory ranges handling
- Address validation

---

## Analytics Use Cases

### Primary Key Structure

The UTA system uses a **Test Request (TR) Centric** data model:

```
Test Request (trname) → Multiple Boards → Multiple Test Cases
         ↓                        ↓                     ↓
   User/Metadata      Physical Inventory      Execution Metrics
```

### Board/PT Mapping Strategy

**Challenge:** `app_board` doesn't store product/core info directly

**Solution:**
1. **Parse** firmware path to extract product info:
   - From `app_board.fwname`: `SAPPHIRE_SIRIUS_EVT1_UFS_3_1_V8_TLC_512Gb_ATM_512GB_P52_RC07_FW00_...`
   - Extract: Product=`SIRIUS`, Version=`V8`, Type=`TLC`, Capacity=`512Gb`

2. **Core Identification** from dump filename:
   - `R7S1-01_H_20250603_143522.bin` → Core=H (Host)
   - `R7S1-01_M_20250603_143523.bin` → Core=M (Management)
   - `R7S1-01_F_20250603_143524.bin` → Core=F (Firmware)
   - `R7S1-01_N_20250603_143525.bin` → Core=N (NCORE)

3. **TR Assignment** from `app_board.trname`:
   - Query SQLite for board → map to TR
   - Group all board data under TR

### Analytics Queries

**Get TR Summary:**
```sql
SELECT trname, COUNT(*) as board_count,
       SUM(CASE WHEN status = 'Testing' THEN 1 ELSE 0 END) as testing,
       SUM(CASE WHEN status = 'Free' THEN 1 ELSE 0 END) as free,
       GROUP_CONCAT(DISTINCT GROUP) as racks
FROM app_board
WHERE trname != 'None'
GROUP BY trname
ORDER BY board_count DESC;
```

**Get Product Distribution:**
- Parse `fwname` from assigned boards
- Group by TR and product

**Get Core Coverage:**
- Count unique cores (H/M/F/N) per board
- Track missing dumps


## System Architecture (UTA Core)

### Core Components

| Component | File | Description |
|-----------|------|-------------|
| **Django App** | `app/` | Main application directory |
| **Models** | `app/models.py` | Database schema definitions |
| **Task Handler** | `app/taskHandler.py` | Test execution task management |
| **Data Layer** | `app/data.py` | REST API endpoints for frontend |
| **Timer Parser** | `app/timerParser.py` | Real-time test status monitoring |
| **Hub Client** | `app/hubClientThreaded.py` | Board communication (ADB/Serial) |
| **Server Socket** | `app/serverSock.py` | Linux server communication |
| **Test List** | `app/tc_list.py` | Test case library management |
| **TR Setup** | `app/tr_setup.py` | Test request setup logic |

### Hardware Communication

The system supports **hybrid connections** to boards:
- **Serial**: `/dev/ttyUSB0`, `COM3` (legacy)
- **ADB (Android Debug Bridge)**: `ADB:0000028c8da117c2`, network `192.168.1.100:5555`
- **Hybrid**: `/dev/ttyUSB0|ADB:0000028c8da117c2` (serial + ADB)

**ADB Server Socket:** Configured via `ADB_SERVER_SOCKET` environment variable (default: `tcp:192.168.1.100:5038`)

### Log Paths

```
PROJECT_ROOT + '/logs/'
├── UTA_FULL_Logs/           # Full test logs
├── Status/                  # Test status files
├── UTF_Linux/              # Tester Linux binaries
└── Firmware_upload/        # Firmware upload directory
```


## Database Schema

### Production Database Snapshot

**Actual Production DB Located:** `/home/gjayeshbhai/uta-analytics/sqlite.db` (276K)

**Current Record Counts:**
| Table | Record Count |
|-------|--------------|
| app_board | 160 |
| app_tcinfo | 0 |
| app_tcresult | 0 |
| app_tclist | 0 |
| app_testrequestinfo | 0 |
| app_autotr | 0 |
| app_testcase | 2 |
| app_fwhistory | 2 |

### Master Tables

#### `app_board` - Hardware Inventory

The single source of truth for all physical boards in the test infrastructure.

| Column | Type | Constraints | Description | Notes |
|--------|------|-------------|-------------|-------|
| `id` | INT | PK AUTO | Internal ID | |
| `boardname` | VARCHAR(128) | UNIQUE | Board identifier | Format: `R1S1-01`, `R9S3-12` |
| `ipaddr` | IP | NOT NULL | Telnet/IP address | ex: `192.168.0.10`, `r7s1.ufs.com` |
| `portaddr` | VARCHAR(18) | NOT NULL | Port/connection string | Ex: `2001`, `/dev/ttyUSB0`, `COM3\|ADB:...` |
| `group` | VARCHAR(16) | NOT NULL | Rack ID | Production: `R7`, `R8` |
| `location` | VARCHAR(8) | NULL | Slot ID | Production: `S1`, `S2`, `S3`, `S4`, `S5` |
| `status` | VARCHAR(16) | NOT NULL | Board state | Values: `Testing`, `Free`, `Keep`, `Passed`, `Unconnected` |
| `selected` | BOOL | NULL | Selection flag | For UI board selection |
| `currenttcname` | VARCHAR(256) | NOT NULL | Currently running test case | Default: `None` |
| `trname` | VARCHAR(256) | NOT NULL | Test request name | Default: `None` (**Primary aggregation key**) |
| `trname2`, `trname3` | VARCHAR(256) | NOT NULL | Additional TRs | For concurrent request support |
| `fwname` | VARCHAR(256) | NULL | Firmware name | Currently loaded on board |
| `progress` | VARCHAR(256) | NULL | Test progress | Format: `3 / 3` or `135014 / 5` |
| `start` | VARCHAR(256) | NULL | Test start time | Format: `2025-06-02 06:26:18` |
| `elapsedtime` | VARCHAR(16) | NULL | Elapsed duration | Format: "26H34M" |
| `profile` | TEXT | NULL | Profile data | **Comma-separated metrics** - see below |

**Production Hardware Layout:**
- **Racks:** R7, R8
- **Shelves:** S1, S2, S3, S4, S5 (per rack)
- **Boards per shelf:** 16
- **Total boards:** 160 (2 racks × 5 shelves × 16 boards)

**Production Board Status Distribution:**
| Status | Count |
|--------|-------|
| Keep | 53 |
| Testing | 48 |
| Free | 44 |
| Passed | 10 |
| Unconnected | 5 |

**Production Board IP Addresses:**
Format patterns: `r{rack}s{shelf}.ufs.com` (e.g., `r7s1.ufs.com`, `r8s3.ufs.com`)

**Reservation Columns (2-20):** Store design/product reservations for test cases
- `reservation`: Design1 reservation TC
- `reservation2-4`: Design2-4 reservation TCs
- `reservation5`: Board Type (Production value: `Root`)
- `reservation6-9`: Product1-4 reservation TCs
- `reservation10-20`: Future/other reservations

**Hardware Hierarchy:**
```
Cluster → Rack (group) → Shelf (location) → Board
    ↓         R7, R8         S1-S5            R7S1-01
```

#### `app_testrequestinfo` - User Test Requests

Manages user-initiated test requests with lifecycle tracking.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INT | PK AUTO | Internal ID |
| `user_id` | INT | FK → auth_user | Requesting user |
| `create_date` | DATE | NULL | Creation date |
| `tr_type` | INT | NOT NULL | Test request type |
| `ims_tr_id` | VARCHAR(128) | NULL | IMS test request ID |
| `ims_tr_title` | VARCHAR(128) | NULL | IMS title |
| `smartdne_test_group` | VARCHAR(128) | NULL | DNE test group |
| `smartdne_test_round` | INT | NULL | DNE test round |
| `trname` | VARCHAR(256) | NOT NULL | Test request name | Primary identifier |
| `status` | VARCHAR(1) | NOT NULL | Request status | `1`=Open, `2`=Closed, `3`=Deleted |
| `startdate` | DATE | NULL | Scheduled start |
| `enddate` | DATE | NULL | Scheduled end |

#### `app_autotr` - Automated Test Requests

Handles scheduling and automation of routine tests.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INT | PK AUTO | Internal ID |
| `trname` | VARCHAR(256) | NOT NULL | Test request name |
| `ffumode` | VARCHAR(16) | NOT NULL | FFU mode parameter |
| `testmode` | VARCHAR(16) | NOT NULL | Test mode parameter |
| `repeatmode` | VARCHAR(16) | NULL | Repeat strategy |
| `rundatetime` | DATETIME | NOT NULL | When to run |
| `targetdatetime` | DATETIME | NOT NULL | Target completion by |
| `timedeltasec` | INT | NOT NULL | Duration in seconds |
| `reservation` | VARCHAR(16) | NOT NULL | Board reservation |
| `userid` | VARCHAR(16) | NOT NULL | User who scheduled |
| `createdatetime` | DATETIME | NOT NULL | When scheduled |
| `status` | VARCHAR(16) | NOT NULL | Execution status | Default: `wait` |
| `hslink` | VARCHAR(16) | NOT NULL | Hardware server link |


### Active Runtime Tables

#### `app_tcinfo` - Active Test Tracking

Tracks active test executions in real-time. One row per active test case.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INT | PK AUTO | Internal ID |
| `boardname` | VARCHAR(128) | NOT NULL | Reference to app_board.boardname |
| `tcname` | VARCHAR(256) | NULL | Test case name |
| `tcstatus` | VARCHAR(256) | NULL | Current status |
| `starttime` | DATETIME | NULL | When test started |
| `elapsedtime` | VARCHAR(256) | NULL | Duration so far |
| `logfilepath` | VARCHAR(1024) | NULL | Path to log file |
| `trresult` | VARCHAR(256) | NULL | Test result | Populated on completion |

**Lifecycle:**
1. Test starts → Row created
2. Test runs → `elapsedtime` updates periodically
3. Test completes → `trresult` filled, row may be archived to TCResult


### Historical Tables

#### `app_tcresult` - Historical Test Results

Stores completed test case results for analysis and reporting.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INT | PK AUTO | Internal ID |
| `trname` | VARCHAR(256) | NOT NULL | Test request name |
| `tcname` | VARCHAR(256) | NOT NULL | Test case name |
| `slot` | VARCHAR(256) | NOT NULL | Slot/board identifier |
| `result` | VARCHAR(1) | NOT NULL | Test result | `0`=Pass, `1`=Fail, `2`=Cancel, `3`=Not Defined |
| `elapsedtime` | INT | NOT NULL | Duration in seconds |
| `starttime` | VARCHAR(256) | NULL | Start timestamp |
| `endtime` | VARCHAR(256) | NULL | End timestamp |
| `summaryFile` | VARCHAR(256) |NOT NULL | Excel summary file path | Format: `\\LAB_SERVER_IP\uta\00.FailLog\YYYYMMDD\Fail_Summary\R9S3-12_YYYYMMDD_HHMMSS...xlsx` |


### Library Tables

#### `app_tclist` - Test Case Library

Script and test case definition repository.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INT | PK AUTO | Internal ID |
| `TCName` | VARCHAR(256) | NOT NULL | Test case name |
| `Param` | VARCHAR(256) | NULL | Parameters |
| `ScriptName` | VARCHAR(256) | NULL | Script filename |
| `Directory1-5` | VARCHAR(256) | NULL | Script directory paths |
| `Author` | VARCHAR(256) | NULL | Script author |
| `CreateDate` | DATETIME | NOT NULL | When test case was created |

Note: `__init__` method sets all Directory fields to empty strings on instantiation.

#### `app_testcase` - Test Case Definitions

General test case categorization.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INT | PK AUTO | Internal ID |
| `testcasetype` | VARCHAR(16) | NULL | Test case type |
| `testcasegroup` | VARCHAR(256) | NULL | Group/category |
| `testcasename` | VARCHAR(1024) | NULL | Detailed name |


### Other Tables

#### `app_reservation` - Board Reservations

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INT | PK AUTO | Internal ID |
| `resertype` | VARCHAR(16) | NULL | Reservation type |
| `resername` | TEXT | NULL | Reservation name |
| `reserboard` | TEXT | NULL | Boards reserved |

#### `app_fwhistory` - Firmware Update History

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INT | PK AUTO | Internal ID |
| `fwdate` | VARCHAR(256) | NULL | Date of firmware update |
| `fwtime` | VARCHAR(256) | NULL | Time of firmware update |
| `fwname` | TEXT | NULL | Firmware name updated |

#### `app_tclistcontrolhistory` - Change Tracking

Audits changes to the test case library.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INT | PK AUTO | Internal ID |
| `parent_id` | INT | NULL | Parent record ID |
| `user_id` | INT | FK → auth_user | User who made change |
| `create_date` | DATETIME | NOT NULL | When change was made |
| `text` | VARCHAR(512) | NULL | Description of change |
| `status` | VARCHAR(1) | NOT NULL | Change type | `0`=Save, `1`=Add, `2`=Edit, `3`=Delete |


## Data Flow

### Test Execution Flow

```
1. User creates TestRequestInfo OR AutoTR scheduled
                ↓
2. Boards assigned from app_board (status → "Occupied")
                ↓
3. TCList scripts selected
                ↓
4. TCinfo row created for each active test case
                ↓
5. Board communicates via hubClientThreaded / serverSock
                ↓
6. timerParser monitors log files for status updates
                ↓
7. Test completes → TCResult row created, TCinfo cleared
                ↓
8. app_board.status → "Free" or "Failed"
```

### Real-time Monitoring (`timerParser.py`)

The system implements a polled monitoring approach that tracks active tests:

**Mechanism:**
- Scans log files in `RESULT_PATH` for markers:
  - `>>>PROCESS X/Y` → Update progress tracking
  - `>>>BEGIN TC_NAME` → Capture test case start
  - `>>>END [PASSED|FAILED]` → Detect completion

**Board Status Update Pattern:**
- Periodically queries `Board.objects.filter(status="Testing")`
- Updates `board.progress`, `board.elapsedtime` fields
- Syncs `board.currenttcname` from log file parsing

**Excerpt from monitoring logic:**
```python
# Parse elapsed time from log files
def elapsed_time(sdate):
    e = datetime.now()
    s = datetime.strptime(sdate, '%Y-%m-%d %H:%M:%S')
    days = (e-s).days
    sec = (e-s).seconds
    hour, sec = divmod(sec, 3600)
    minute, sec = divmod(sec, 60)
    if days > 0:
        hour = days*24 + hour
    total_time = str(hour)+"H"+str(minute) + "M"
    return total_time
```


## Key Code Patterns

### Board Lookup Pattern

```python
# Standard board retrieval
board = Board.objects.get(boardname=boardname_or_slot)

# Get physical location
rack = board.group  # Ex: "ADB:0000028c8da117c2" or "R1"
slot = board.location  # Ex: "R1" or "S1"

# Get active test
trname = board.trname
tcname = board.currenttcname
```

### Test Status Detection

Markers in log files determine test status:
- `>>>BEGIN` - Test case started
- `>>>END PASSED` - Test passed
- `>>>END FAILED` - Test failed
- `>>>END HKRES` - Hong Kong response
- `>>>PROCESS X/Y` - Progress indicator (X current, Y total)


## Hardware Configuration Examples

### Board Record Example (Production):

```
boardname: R7S1-01
ipaddr: r7s1.ufs.com
portaddr: 2001
group: R7
location: S1
status: Testing
trname: Trail_RUN_Rajesh
fwname: SAPPHIRE_SIRIUS_EVT1_UFS_3_1_V8_TLC_512Gb_ATM_512GB_P52_RC07_FW00_1ffe5b4ef_20250521.bin
currenttcname: TL_INFO
progress: 135014 / 5
start: 2025-06-02 06:26:18
elapsedtime: 26H34M
profile: [see below - comma-separated metrics]
```

### Production Board Record Summary (RACK8_TRAILRUN_RAJESH Test Request):

**Cross-Rack Distribution:**
| Test Request | Boards | Racks |
|--------------|--------|-------|
| RACK8_TRAILRUN_RAJESH | 64 | R7, R8 |
| Trail_RUN_Rajesh | 54 | R7, R8 |
| RAJESH_TRAIL_RUN_512GB | 40 | R7 |

**Board Status Snapshot (per TR):**
```
RACK8_TRAILRUN_RAJESH on R7S1-02: Free | Net Connected
RACK8_TRAILRUN_RAJESH on R7S1-03: Keep | HPB_Initialize | progress: 3 / 3
RACK8_TRAILRUN_RAJESH on R7S2-09: Keep | HPB_Initialize | progress: 3 / 3
... (64 boards total across R7 and R8)
```

### Naming Conventions

- **Board Names:** `R{rack}S{shelf}-{number}` → `R7S1-01`, `R8S3-12`
- **Test Request Names:** User-defined or auto-generated
  - Production examples: `Trail_RUN_Rajesh`, `RACK8_TRAILRUN_RAJESH`, `RAJESH_TRAIL_RUN_512GB`, `512GB`
- **Firmware Names:** `{PRODUCT}_V{version}_P{patch}_RC{rc}.bin`
  - Production example: `SAPPHIRE_SIRIUS_EVT1_UFS_3_1_V8_TLC_512Gb_ATM_512GB_P52_RC07_FW00_1ffe5b4ef_20250521.bin`
- **Log Files:** `{slot}_{timestamp}_{type}_{product}_{firmware}_{test}_params}.log`


## Current Database State

**Production Database:** `/home/gjayeshbhai/uta-analytics/sqlite.db` (276K)

| Table | Record Count |
|-------|--------------|
| app_board | 160 |
| app_tcinfo | 0 |
| app_tcresult | 0 |
| app_tclist | 0 |
| app_testrequestinfo | 0 |
| app_autotr | 0 |
| app_testcase | 2 |
| app_fwhistory | 2 |

**Production Hardware Inventory:**
- 2 Racks (R7, R8)
- 5 Shelves per rack (S1-S5)
- 16 Boards per shelf
- **Total: 160 physical boards**


## Production Data Profile

### `board.profile` Field - Health Metrics

The `profile` column contains comma-separated metrics representing board health/statistics.

**Sample Profile Values:**
```
2121,1,1000,1,0,0,10,0,4309874,0,1,0,20241124,168,3083,0,2,4309872
2136,14,990,1,0,0,7,0,4344435,0,1,0,20250118,167,3083,0,2,4344433
8,1,5,79,5,15,62,0,16695,0,1,1,20250521,1012591,212344,1,221,16474
```

These metrics appear to track flash memory and test statistics but require further documentation from the original UTA team to decode fully.

**Key Observation:** Each comma-separated value appears to represent a specific metric type, likely:
- Erase counts
- Block health
- Test statistics
- Firmware/firmware date stamps

## Multi-Server Deployment Context

The system is designed for deployment across multiple UTA servers, each hosting different board hardware:

- **Multiple Servers:** Each server runs independent Django + SQLite instance
- **Non-static Hardware:** Boards are NOT fixed to servers - `boardname` identifies the board globally
- **Rack/Slot Mapping:** Physical hardware hierarchy stored in `board.group` and `board.location`
- **ADB Connections:** Boardsconnect via ADB (often through Windows machine hosting the test runner)

**Implications for Analytics:**
1. Board identity (`boardname`) is the stable identifier across deployments
2. Additional context needed: which server is hosting which boards at any time
3. Hardware location (`group`/`location`) may be more stable than server IP
4. Log file paths are server-specific → need server attribution


## Files of Interest for Analytics Integration

### Model Definitions
- `app/models.py` - Complete schema with field types and relationships

### Active Monitoring
- `app/timerParser.py` - Real-time test status parsing from log files
- `app/data.py` - REST API endpoints exposing test data to frontend
- `app/taskHandler.py` - Task queue management for test execution

### Board Communication
- `app/hubClientThreaded.py` - Hybrid port parsing, ADB push/pull operations
- `app/serverSock.py` - Linux server communication (for remote test execution)

### Test Management
- `app/tc_list.py` - Test case library CRUD operations
- `app/tr_setup.py` - Test request setup and initialization

### Logging & Files
- `app/FailParser.py` - Fail log parsing and queue management
- `app/failLogAnalyzer.py` - Deep analysis of test failure logs
- `app/Push_TC_DB.py` - Pushing test results to database

### Configuration
- `halo2/settings.py` - Log paths, database config, server network settings


## SQL Query Patterns

### Get Active Tests
```sql
SELECT boardname, trname, currenttcname, elapsedtime, progress
FROM app_board
WHERE status IN ('Testing', 'Occupied');
```

### Get Board by Slot
```sql
SELECT * FROM app_board WHERE boardname = 'R9S3-12';
```

### Get Historical Results for Slot
```sql
SELECT trname, tcname, result, starttime, endtime, elapsedtime, summaryFile
FROM app_tcresult
WHERE slot = 'R9S3-12'
ORDER BY starttime DESC
LIMIT 100;
```

### Get Boards by Rack
```sql
SELECT * FROM app_board
WHERE `group` = 'ADB:0000028c8da117c2'
ORDER BY location, boardname;
```


## Related Files in Memory

- [[uta-analysis-approach]] (to be created) - Analytics integration strategy


## Analytics Use Cases

### Primary Key Structure

The UTA system uses a **Test Request (TR) Centric** data model:

```
Test Request (trname) → Multiple Boards → Multiple Test Cases
         ↓                        ↓                     ↓
   User/Metadata      Physical Inventory      Execution Metrics
```

**Primary Table Relationships for Analytics:**

1. **TR → Boards Mapping:** `app_board.trname` field
2. **TR Aggregation:** Group boards by `trname` to get test request status
3. **Board Inventory:** `app_board.group`, `app_board.location` for physical topology
4. **Firmware Tracking:** `app_board.fwname` for firmware version distribution
5. **Status Tracking:** `app_board.status` for real-time board state

### Key Analytics Queries

**Get Test Request Summary:**
```sql
SELECT trname, COUNT(*) as board_count,
       SUM(CASE WHEN status = 'Testing' THEN 1 ELSE 0 END) as testing,
       SUM(CASE WHEN status = 'Free' THEN 1 ELSE 0 END) as free,
       GROUP_CONCAT(DISTINCT GROUP) as racks
FROM app_board
WHERE trname != 'None'
GROUP BY trname
ORDER BY board_count DESC;
```

**Get Firmware Distribution per TR:**
```sql
SELECT trname, fwname, COUNT(*) as board_count
FROM app_board
WHERE trname != 'None' AND fwname IS NOT NULL
GROUP BY trname, fwname;
```

**Get Board Status by Rack:**
```sql
SELECT \`group\`, location, status, COUNT(*) as board_count
FROM app_board
GROUP BY \`group\`, location, status
ORDER BY \`group\`, location, status;
```


## New Analytics Data Model

### TR-Centric Aggregation

**Primary Data Hierarchy:**
```
Test Request (TR)
    ├── Board R7S1-01
    │   ├── Core H Dump → JSON → ClickHouse
    │   ├── Core M Dump → JSON → ClickHouse
    │   ├── Core F Dump → JSON → ClickHouse
    │   └── Core N Dump → JSON → ClickHouse
    ├── Board R7S1-02
    │   └── ... (all cores)
    └── Board R8S1-01
        └── ... (all cores)
```

### Data Ingestion Pipeline

**Step 1: File Watching (UTA Server Side)**
- Watch directory: `/uta/dumps/`
- Detect new .bin files with pattern: `board_core_timestamp.bin`
- Wait for file write completion (size stable for N seconds)
- Emit event when file is ready

**Step 2: Metadata Extraction**
- Parse filename: `R7S1-01_H_20250603_143522.bin`
  - Board: `R7S1-01`
  - Core: `H`
  - Timestamp: `20250603_143522`
- Query SQLite for board metadata:
  - TR name: `app_board.trname`
  - Firmware path: `app_board.fwname`
  - Status: `app_board.status`

**Step 3: Streaming**
- Transfer .bin file to analytics server
- Package with metadata in stream message
- Topic or queue: `raw-dumps`

**Step 4: Product/Core Resolution**
- Parse firmware path for product info:
  - From `fwname`: `SAPPHIRE_SIRIUS_EVT1_UFS_3_1_V8_TLC_512Gb_ATM_512GB_P52_RC07_FW00`
  - Extract: `product=SIRIUS`, `version=V8`, `type=TLC`, `capacity=512Gb`
- Map core from filename: `H/M/F/N`
- Select appropriate AXF based on product + core

**Step 5: AXF Parsing**
- Load cached AXF layout for product/core
- Decode binary dump using `map_bin.py` logic
- Generate structured JSON variable/snapshot
- Handle: arrays, structs, pointers, enums, bitfields

**Step 6: ClickHouse Ingestion**
- JSON → ClickHouse table structure
- Table: `dump_snapshots`
- Columns: `trname`, `boardname`, `core`, `timestamp`, `product`, `variable_name`, `variable_data_json`
- Indexing: `trname`, `boardname`, `product`, `timestamp`

### Sample ClickHouse Schema

```sql
CREATE TABLE dump_snapshots (
    trname String,
    boardname String,
    core LowCardinality(String),           -- H/M/F/N
    timestamp DateTime64(3),
    product LowCardinality(String),
    product_version String,                -- V8, etc.
    variable_name String,
    variable_data String,                  -- JSON string of decoded value
    raw_bin_path String,                   -- Reference to original .bin
    ingested_at DateTime64(3) DEFAULT now64(3)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (trname, boardname, core, variable_name, timestamp)
TTL timestamp + INTERVAL 90 DAY;
```


## Product AXF Library

**Known Products and Cores:**

| Product | Cores | AXF Files |
|---------|-------|-----------|
| UFS_UHP | H,F,M,N | `UFS_UHP.axf` (current single file) |
| SAPPHIRE | F,M | `SAPPHIRE_IT_ASIC_FCore.axf`, `SAPPHIRE_IT_ASIC_MCore.axf` |
| SIRIUS | H | `NCORE0_SIRIUS_V8_TLC.axf` |

**AXF Resolution Strategy:**
1. Default lookup: product → core → specific AXF
2. Fallback: use generic AXF if product-specific not found
3. Cache parsed layouts for performance

**Layout Generation (One-Time or on Update):**
```bash
# Generate all product layouts
for axf in *.axf; do
    python process_elf.py "$axf"
done
# Output: layout/<product>.json
```


## Core Identification

**Board Core Types:**
- **H (Host):** Main processor core, handles UFS command processing
- **M (Management):** Management core, handles device operations
- **F (Firmware):** Firmware execution core
- **N (NCORE/SMR):** Specialized core for specific tasks (e.g., NCORE0)

**Core Mapping from Dump Filename:**
```
R7S1-01_H_20250603_143522.bin → Core: H
R7S1-01_M_20250603_143523.bin → Core: M
R7S1-01_F_20250603_143524.bin → Core: F
R7S1-01_N_20250603_143525.bin → Core: N
```


## Firmware filename parsing metadata
**From Firmware Path:**

Example: `SAPPHIRE_SIRIUS_EVT1_UFS_3_1_V8_TLC_512Gb_ATM_512GB_P52_RC07_FW00_1ffe5b4ef_20250521.bin`

| Component | Value | Meaning |
|-----------|-------|---------|
| Product | `SIRIUS` | Main product line |
| Interface | `UFS_3_1` | UFS version |
| Version | `V8` | Silicon version |
| Type | `TLC` | NAND flash type |
| Density | `512Gb` | Die density |
| Target | `ATM` | Customer/Application |
| Capacity | `512GB` | Total device capacity |
| Patch | `P52` | Patch version |
| RC | `RC07` | Release candidate |
| FW | `FW00` | Firmware level |
| Build ID | `1ffe5b4ef` | Build hash |
| Date | `20250521` | Build date |

**Parsing Strategy:**
- Regex map for each component
- Required fields for reliable matching
- Fallback options for missing components


## Dashboard and Visualization

### Data Complexity Challenge

**Raw AXF Output Structure:**
- Deeply nested JSON (10-20+ levels)
- Arrays of arrays of structs
- Mixed types (int, float, strings, bool)

**Example Variable Output:**
```json
{
  "version": 1,
  "flags": {
    "enabled": true,
    "mode": 2
  },
  "counters": [
    {"id": 0, "value": 1234},
    {"id": 1, "value": 5678}
  ],
  "health_map": {
    "healthy": [0, 1, 2, 3],
    "degraded": [4],
    "failed": []
  }
}
```

### Visualization Approaches

**Option 1: Raw JSON Dashboard**
- Grafana plugins that directly render JSONPath
- User constructs queries for specific paths
- Pros: No preprocessing, flexible
- Cons: Complex for users, limited query capabilities

**Option 2: Preprocessed Metrics**
- Backend service extracts meaningful metrics from JSON
- Separate aggregation tables in ClickHouse
- Pros: Dashboards easier to build
- Cons: Need to define metrics per variable

**Option 3: Hybrid Approach**
- Store raw JSON for flexibility
- Compute key metrics on insert or scheduled job
- Grafana queries both as needed
- Pros: Best of both worlds
- Cons: More storage/maintenance


## SQLite to Analytics Mapping

**Key Mapping Table:**

| Analytics Need | UTA Source | Field Path | Notes |
|----------------|------------|------------|-------|
| Test Request ID | app_board | trname | Primary aggregation key |
| Board ID | app_board | boardname | `R7S1-01` format |
| Physical Location | app_board | group, location | Rack R7, Shelf S1 |
| Product | app_board | fwname | Parse from firmware path |
| Core | Filename | `board_core_timestamp.bin` | Extract `core` suffix |
| Test Status | app_board | status | Testing, Free, Keep, Passed |
| Firmware Version | app_board | fwname | Full path |
| Health Metrics | app_board | profile | Comma-separated (needs parsing) |
| Test Progress | app_board | progress | `X / Y` or `current / total` |
| Test Timing | app_board | start, elapsedtime | Start time, duration |


## Technology Stack Summary

### Legacy (Deprecated)
- Vector → Kafka → Python Parsers → ClickHouse → Grafana

### New Stack
**UTA Server Side:**
- Python File Watcher (inotify/Watchdog)
- Metadata Extractor
- HTTP/Stream Client

**Analytics Side:**
- ClickHouse (storage)
- AXF Parsing Library (Python)
- Product/Core Config Registry
- Optional: Preprocessing Service
- Grafana (visualization)

**Infrastructure:**
- SQLite (UTA metadata source)
- Kafka/Queue (bin streaming - optional)
- HTTP/TCP (file transfer)


## Open Questions & Considerations

### File Streaming Strategy
- Direct HTTP upload vs. message queue
- Compression of binary files?
- Buffer/cleanup of original .bin files?

### AXF Layout Management
- How to detect AXF updates?
- Layout regeneration logic?
- Multi-version support?

### Performance Considerations
- Trade dump parsing overhead vs. freshness
- Batch processing vs. real-time?
- ClickHouse insert batch size?

### Product/AXF Mapping
- What if product info can't be parsed?
- Fallback AXF selection?
- Manual override mechanism?

### Core Gaps
- Some boards may not have all cores
- What to do with missing core dumps?
- Dashboard handling of incomplete data?
