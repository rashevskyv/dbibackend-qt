"""
DBI Protocol Constants
"""

# DBI Protocol Commands
CMD_ID_EXIT = 0
CMD_ID_LIST_OLD = 1
CMD_ID_FILE_RANGE = 2
CMD_ID_LIST = 3

CMD_ID_PACKAGE_STATUS = 4
CMD_ID_STORAGE_INFO = 5
# Kefir Hub -> PC: the console's view of the queue after it planned it:
# selection and target as the console has them (a tick removed on the console
# must not come back from here), where each Auto package will really go and
# its install size, so the PC can draw the same storage projection as the Hub.
CMD_ID_QUEUE_PLAN = 6

CMD_TYPE_REQUEST = 0
CMD_TYPE_RESPONSE = 1
CMD_TYPE_ACK = 2

BUFFER_SEGMENT_DATA_SIZE = 0x100000  # 1 MB
METADATA_THRESHOLD = 100 * 1024  # 100KB

LIST_EXT_SPHA = 0x53504841  # 'SPHA'
LIST_EXT_SPHQ = 0x51485053  # 'SPHQ'
SPHQ_EMPTY_MARKER = "::SPHQ::\n"
SPHQ_REV_PREFIX = "::SPHQ_REV::|"

# Target Locations
TARGET_AUTO = 0
TARGET_SD = 1
TARGET_NAND = 2

# Package Status Codes
STATUS_INSTALLED = 0
STATUS_USER_SKIPPED = 1
STATUS_ALREADY_INSTALLED = 2
STATUS_FAILED = 3

# Queue plan payload: [count: u32][revision: u32] then per package
# [selected: u8][target: u8][planned: u8 (1 = SD, 2 = NAND)][flags: u8][install_size: u64][name_len: u32][name].
# flags bit0 = analysis ok, bit1 = title already installed,
# bit2 = takes no space (installed and the skip mode in force will skip it),
# bit3 = update or DLC whose base game is not on the console.
QUEUE_PLAN_HEADER = '<II'
QUEUE_PLAN_RECORD = '<BBBBQI'
PLAN_FLAG_ANALYSIS_OK = 1
PLAN_FLAG_ALREADY_INSTALLED = 2
PLAN_FLAG_NO_SPACE = 4
PLAN_FLAG_NO_BASE = 8

# "Already installed" mode the PC sets on the console, sent in the SPHQ revision
# line ("::SPHQ_REV::|rev|<mode>|0"). 0 = leave it to the console's setting.
SKIP_MODE_CONSOLE = 0
SKIP_MODE_REINSTALL = 1
SKIP_MODE_SKIP = 2
SKIP_MODE_PROMPT = 3


def parse_queue_plan(payload: bytes):
    """Decode one queue plan into (revision, [dict]). Truncated input raises ValueError."""
    import struct
    head = struct.calcsize(QUEUE_PLAN_HEADER)
    rec = struct.calcsize(QUEUE_PLAN_RECORD)
    if len(payload) < head:
        raise ValueError('queue plan header truncated')
    count, revision = struct.unpack_from(QUEUE_PLAN_HEADER, payload, 0)
    off = head
    items = []
    for _ in range(count):
        if len(payload) < off + rec:
            raise ValueError('queue plan record truncated')
        selected, target, planned, flags, size, name_len = struct.unpack_from(QUEUE_PLAN_RECORD, payload, off)
        off += rec
        if len(payload) < off + name_len:
            raise ValueError('queue plan name truncated')
        name = payload[off:off + name_len].decode('utf-8', errors='replace')
        off += name_len
        items.append({
            'name': name,
            'selected': bool(selected),
            'target': target,
            'planned_sd': planned == TARGET_SD,
            'install_size': size,
            'analysis_ok': bool(flags & PLAN_FLAG_ANALYSIS_OK),
            'already_installed': bool(flags & PLAN_FLAG_ALREADY_INSTALLED),
            'no_space': bool(flags & PLAN_FLAG_NO_SPACE),
            'no_base': bool(flags & PLAN_FLAG_NO_BASE),
        })
    return revision, items


def plan_projection(items, focus_name=None):
    """What the selected packages will take on each drive, the way the Hub sums it
    for its storage bars: (nand_required, sd_required, nand_focus, sd_focus)."""
    nand_req = sd_req = nand_focus = sd_focus = 0
    for it in items:
        if not (it['selected'] and it['analysis_ok']) or it.get('no_space'):
            continue
        size = it['install_size']
        if it['planned_sd']:
            sd_req += size
            if it['name'] == focus_name:
                sd_focus = size
        else:
            nand_req += size
            if it['name'] == focus_name:
                nand_focus = size
    return nand_req, sd_req, nand_focus, sd_focus


def build_list_payload(files, selected, targets, extension, revision, skip_mode=SKIP_MODE_CONSOLE):
    """Encode one ordered DBI/SPHA/SPHQ list snapshot."""
    if extension == LIST_EXT_SPHQ:
        lines = [f"{SPHQ_REV_PREFIX}{revision}|{skip_mode}|0"] if revision > 0 else []
        for name, path in files:
            try:
                size = path.stat().st_size
            except Exception:
                size = 0
            lines.append(f"{name}|{size}|{int(name in selected)}|{targets.get(name, TARGET_AUTO)}")
        if not files:
            lines.append(SPHQ_EMPTY_MARKER.strip())
    elif extension == LIST_EXT_SPHA:
        lines = []
        for name, path in files:
            if name not in selected:
                continue
            try:
                size = path.stat().st_size
            except Exception:
                size = 0
            lines.append(f"{name}|{size}")
    else:
        lines = [name for name, _ in files if name in selected]
    return (("\n".join(lines) + "\n") if lines else "").encode('utf-8')
