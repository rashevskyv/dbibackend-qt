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


def build_list_payload(files, selected, targets, extension, revision):
    """Encode one ordered DBI/SPHA/SPHQ list snapshot."""
    if extension == LIST_EXT_SPHQ:
        lines = [f"{SPHQ_REV_PREFIX}{revision}|0|0"] if revision > 0 else []
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
