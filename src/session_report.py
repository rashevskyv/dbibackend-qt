"""
End-of-session report: what the console installed, skipped and failed, updates and
DLC whose base game is not on the console, and why each failed package failed.
Pure text building, so it is tested without a window (tests/test_session_report.py).
"""
import re
from datetime import datetime
from typing import Dict, Iterable, Optional, Tuple

from . import dbi_protocol

# Kefir Hub's own result descriptions, in the order of SphairaResult in
# sphaira/include/defines.hpp (module 505). New codes are appended there, so
# append here too; the order is the code.
SPHAIRA_RESULTS = (
    'TransferCancelled', 'StreamBadSeek', 'FsTooManyEntries', 'FsNewPathTooLarge', 'FsInvalidType',
    'FsEmpty', 'FsAlreadyRoot', 'FsNoCurrentPath', 'FsBrokenCurrentPath', 'FsIndexOutOfBounds',
    'FsFsNotActive', 'FsNewPathEmpty', 'FsLoadingCancelled', 'FsBrokenRoot', 'FsUnknownStdioError',
    'FsReadOnly', 'FsNotActive', 'FsFailedStdioStat', 'FsFailedStdioOpendir', 'NroBadMagic',
    'NroBadSize', 'AppFailedMusicDownload', 'CurlFailedEasyInit', 'DumpFailedNetworkUpload',
    'UnzOpen2_64', 'UnzGetGlobalInfo64', 'UnzLocateFile', 'UnzGoToFirstFile', 'UnzGoToNextFile',
    'UnzOpenCurrentFile', 'UnzGetCurrentFileInfo64', 'UnzReadCurrentFile', 'ZipOpen2_64',
    'ZipOpenNewFileInZip', 'ZipWriteInFileInZip', 'MmzBadLocalHeaderSig', 'MmzBadLocalHeaderRead',
    'FileBrowserFailedUpload', 'FileBrowserDirNotDaybreak', 'AppstoreFailedZipDownload',
    'AppstoreFailedMd5', 'AppstoreFailedParseManifest', 'GameBadReadForDump',
    'GameEmptyMetaEntries', 'GameMultipleKeysFound', 'GameNoNspEntriesBuilt',
    'GameMoveNoAppManager', 'GameMoveNotEnoughSpace', 'KeyMissingNcaKeyArea', 'KeyMissingTitleKek',
    'KeyMissingMasterKey', 'KeyFailedDecyptETicketDeviceKey', 'NcaFailedNcaHeaderHashVerify',
    'NcaBadSigKeyGen', 'NcaBadMagic', 'GcBadReadForDump', 'GcEmptyGamecard', 'GcBadXciMagic',
    'GcBadXciRomSize', 'GcFailedToGetSecurityInfo', 'GhdlEmptyAsset', 'GhdlFailedToDownloadAsset',
    'GhdlFailedToDownloadAssetJson', 'GhdlFileTooLarge', 'ThemezerFailedToDownloadThemeMeta',
    'ThemezerFailedToDownloadTheme', 'MainFailedToDownloadUpdate', 'UsbDsBadDeviceSpeed',
    'NspBadMagic', 'XciBadMagic', 'XciSecurePartitionNotFound', 'EsBadTitleKeyType',
    'EsPersonalisedTicketDeviceIdMissmatch', 'EsFailedDecryptPersonalisedTicket',
    'EsBadDecryptedPersonalisedTicketSize', 'EsBadTicketSize', 'EsInvalidTicketBadRightsId',
    'EsInvalidTicketFromatVersion', 'EsInvalidTicketKeyType', 'EsInvalidTicketKeyRevision',
    'OwoBadArgs', 'UsbCancelled', 'UsbBadMagic', 'UsbBadVersion', 'UsbBadCount',
    'UsbBadBufferAlign', 'UsbBadTransferSize', 'UsbEmptyTransferSize', 'UsbOverflowTransferSize',
    'UsbBadTotalSize', 'UsbGoldleafFailed', 'UsbUploadBadMagic', 'UsbUploadExit',
    'UsbUploadBadCount', 'UsbUploadBadTransferSize', 'UsbUploadBadTotalSize',
    'UsbUploadBadCommand', 'YatiContainerNotFound', 'YatiNcaNotFound', 'YatiInvalidNcaReadSize',
    'YatiInvalidNcaSigKeyGen', 'YatiInvalidNcaMagic', 'YatiInvalidNcaSignature0',
    'YatiInvalidNcaSignature1', 'YatiInvalidNcaSha256', 'YatiNczSectionNotFound',
    'YatiInvalidNczSectionCount', 'YatiNczBlockNotFound', 'YatiInvalidNczBlockVersion',
    'YatiInvalidNczBlockType', 'YatiInvalidNczBlockTotal', 'YatiInvalidNczBlockSizeExponent',
    'YatiInvalidNczZstdError', 'YatiTicketNotFound', 'YatiInvalidTicketBadRightsId',
    'YatiCertNotFound', 'YatiNcmDbCorruptHeader', 'YatiNcmDbCorruptInfos', 'SmbConnectionFailed',
    'SmbNotSupported', 'SaveSyncFailed', 'StreamUnexpectedEof', 'TranslationRemoveExistingFailed',
    'TransferInterrupted', 'NtpNoConnection', 'NtpResolveFailed', 'NtpSocketFailed',
    'NtpSendFailed', 'NtpRecvFailed', 'NtpBadReply', 'NtpSetTimeFailed', 'NetNoConnection',
    'YatiHttpReadFailed', 'ArchiveRead',
)

# plain words for the codes an install actually ends with.
EXPLAIN = {
    'UsbBadCount': 'The PC did not send this file: it is missing or unreadable on the PC.',
    'TransferCancelled': 'Cancelled on the console.',
    'UsbCancelled': 'Cancelled on the console.',
    'TransferInterrupted': 'The transfer stopped half way (cable or PC).',
    'StreamUnexpectedEof': 'The file ends too early. It is probably incomplete.',
    'YatiContainerNotFound': 'Not a valid NSP, NSZ or XCI file.',
    'NspBadMagic': 'Not a valid NSP file (bad header).',
    'XciBadMagic': 'Not a valid XCI file (bad header).',
    'YatiNcaNotFound': 'The file is incomplete: content listed in its metadata is missing.',
    'YatiInvalidNcaSha256': 'The file is damaged: a content hash does not match.',
    'YatiInvalidNczZstdError': 'The NSZ file is damaged: decompression failed.',
    'YatiTicketNotFound': 'The game needs a ticket (title key) that is not in the file.',
    'YatiInvalidTicketBadRightsId': 'The ticket in the file belongs to another title.',
    'YatiCertNotFound': 'The certificate for the ticket is missing from the file.',
    'KeyMissingMasterKey': 'The console has no key for this game: update the firmware.',
    'KeyMissingTitleKek': 'The console has no key for this game: update the firmware.',
    'KeyMissingNcaKeyArea': 'The console has no key for this game: update the firmware.',
    'NcaBadSigKeyGen': 'The game needs a newer firmware.',
    'YatiInvalidNcaSigKeyGen': 'The game needs a newer firmware.',
    'YatiNcmDbCorruptHeader': 'The console content database could not be read.',
    'YatiNcmDbCorruptInfos': 'The console content database could not be read.',
}

MODULES = {1: 'Kernel', 2: 'FS', 5: 'NCM', 16: 'NS', 140: 'USB', 505: 'Kefir Hub'}


def describe_result(code: int) -> str:
    """'2505-0084 UsbBadCount: The PC did not send this file...' for a Horizon result."""
    module, desc = code & 0x1FF, (code >> 9) & 0x1FFF
    head = f'{2000 + module:04d}-{desc:04d}'
    if module == 505 and desc < len(SPHAIRA_RESULTS):
        name = SPHAIRA_RESULTS[desc]
        return f'{head} {name}: {EXPLAIN[name]}' if name in EXPLAIN else f'{head} {name}'
    if module == 2 and 30 <= desc <= 45:
        return f'{head} FS: not enough free space.'
    return f'{head} {MODULES.get(module, f"module {module}")}'


_TID = re.compile(r'\[([0-9A-Fa-f]{16})\]')


def title_id(name: str) -> int:
    m = _TID.search(name)
    return int(m.group(1), 16) if m else 0


def base_title_id(tid: int) -> int:
    """Base game of an update (...800) or a DLC (base + 0x1000 + n); 0 for a base game."""
    if not tid or tid & 0xFFF == 0:
        return 0
    if tid & 0xFFF == 0x800:
        return tid & ~0xFFF
    return (tid & ~0xFFF) - 0x1000


def build_report(
    results: Dict[str, Tuple[int, int]],
    not_reached: Iterable[str],
    plan: Dict[str, dict],
    pc_errors: Dict[str, str],
    started: Optional[datetime],
    finished: datetime,
) -> Tuple[str, str, bool]:
    """(one-line summary, full text, clean: nothing failed, missed or lacks a base). results: name -> (package status, result code),
    as the console reported them; plan: the console's last queue plan by name."""
    by_status = {s: [n for n, (st, _) in results.items() if st == s] for s in range(4)}
    installed = by_status[dbi_protocol.STATUS_INSTALLED]
    already = by_status[dbi_protocol.STATUS_ALREADY_INSTALLED]
    user_skipped = by_status[dbi_protocol.STATUS_USER_SKIPPED]
    failed = by_status[dbi_protocol.STATUS_FAILED]
    not_reached = [n for n in not_reached if n not in results]

    # a base game installed in this same session counts, even though the plan
    # was made before it was on the console.
    bases_now = {title_id(n) for n in installed + already}
    no_base = [n for n in installed + already
               if plan.get(n, {}).get('no_base') and base_title_id(title_id(n)) not in bases_now]

    summary = (f'Installed {len(installed)}, already installed {len(already)}, '
               f'failed {len(failed)}, not reached {len(not_reached)}, without base {len(no_base)}')
    lines = [f'DBI Backend Qt: session report, {finished:%Y-%m-%d %H:%M}']
    if started:
        secs = int((finished - started).total_seconds())
        lines.append(f'Time: {secs // 3600:02d}:{secs // 60 % 60:02d}:{secs % 60:02d}')
    lines += [
        '',
        f'Installed:          {len(installed)}',
        f'Already installed:  {len(already)} (skipped)',
        f'Skipped by user:    {len(user_skipped)}',
        f'Failed:             {len(failed)}',
        f'Not reached:        {len(not_reached)} (still ticked when the session ended)',
    ]
    if not plan:
        lines.append('Without base game:  unknown (the console sent no queue plan)')
    else:
        lines.append(f'Without base game:  {len(no_base)}')

    if failed:
        lines += ['', 'FAILED']
        for n in failed:
            lines.append(f'- {n}')
            lines.append(f'    Console: {describe_result(results[n][1])}')
            if n in pc_errors:
                lines.append(f'    PC: {pc_errors[n]}')
    if no_base:
        lines += ['', 'WITHOUT BASE GAME (update or DLC installed, the base game is not on the console)']
        lines += [f'- {n}' for n in no_base]
    for title, names in (('NOT REACHED', not_reached), ('SKIPPED BY USER', user_skipped)):
        if names:
            lines += ['', title] + [f'- {n}' for n in names]
    clean = not (failed or not_reached or no_base)
    return summary, '\n'.join(lines) + '\n', clean
