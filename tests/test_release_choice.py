"""Per-game choice over analysed releases (the data the add dialog edits)."""
from pathlib import Path

from src import release_choice as rc
from src.release_analyzer import analyze

BASE = 'Game [0100B7C00933A000][v0].nsp'
UPD4 = 'Game [0100B7C00933A800][v262144].nsp'
UPD2 = 'Game [0100B7C00933A800][v131072].nsp'
TID = 0x0100B7C00933A000
MOD = 'Russian Language Mod'
ADDON = f'{MOD}/Addon - English Voiceover'


def touch(base: Path, rels):
    for r in rels:
        (base / r).parent.mkdir(parents=True, exist_ok=True)
        (base / r).write_bytes(b'x')


def phoenix():
    return analyze([BASE, UPD4, f'{MOD}/atmosphere/contents/0100B7C00933A000/romfs/t.bin', f'{MOD}/{UPD2}',
                    f'{ADDON}/atmosphere/contents/0100B7C00933A000/romfs/v.bin'])


def test_plain_package_folder_is_not_smart():
    assert not rc.is_smart(analyze([BASE, UPD4]))
    assert rc.is_smart(phoenix())


def test_addon_pulls_its_mod_and_unticking_the_mod_drops_the_addon():
    rel = phoenix()
    choice = {TID: set()}
    rc.toggle(rel, choice, TID, ADDON, True)
    assert choice[TID] == {ADDON, MOD}
    assert rc.conflicts(rel, choice) == []
    rc.toggle(rel, choice, TID, MOD, False)
    assert choice[TID] == set()


def test_packages_follow_the_mod_update(tmp_path):
    rel = phoenix()
    touch(tmp_path, [BASE, UPD4, f'{MOD}/{UPD2}'])
    with_mod = rc.packages(rel, rc.defaults(rel), tmp_path)
    assert with_mod == [tmp_path / BASE, tmp_path / MOD / UPD2]
    assert rc.packages(rel, {TID: set()}, tmp_path) == [tmp_path / BASE, tmp_path / UPD4]
    assert rc.sd_file_count(rel, rc.defaults(rel)) == 1


def test_missing_files_and_unknown_packages(tmp_path):
    rel = analyze([BASE, 'Taiko DLC.nsp', 'switch/port/port.nro'])
    touch(tmp_path, ['Taiko DLC.nsp'])   # the base is in a release listing but not on disk
    assert rc.packages(rel, rc.defaults(rel), tmp_path) == [tmp_path / 'Taiko DLC.nsp']


def test_shared_ports_are_all_ticked():
    rel = analyze(['DKC 1 [03DB1DA917792000][v0].nsp', 'DKC 2 [03DB1CAB43D78000][v0].nsp',
                   'switch/dkc1/dkc1.nro', 'switch/dkc2/dkc2.nro'])
    choice = rc.defaults(rel)
    assert choice[rc.ORPHANS] == {o.key for o in rel.orphans} and len(rel.orphans) == 2
    rc.toggle(rel, choice, rc.ORPHANS, rel.orphans[0].key, False)
    assert rc.sd_file_count(rel, choice) == 1
    assert rc.summary(rel, choice) == 'dkc2'


def test_two_mods_with_different_updates_is_a_conflict():
    rel = analyze([BASE, UPD4, f'A/{UPD2}', 'A/atmosphere/contents/0100B7C00933A000/romfs/a',
                   'B/Game [0100B7C00933A800][v65536].nsp', 'B/atmosphere/contents/0100B7C00933A000/romfs/b'])
    choice = rc.defaults(rel)
    assert choice[TID] == set()   # two mods: none by default
    rc.toggle(rel, choice, TID, 'A', True)
    rc.toggle(rel, choice, TID, 'B', True)
    assert len(rc.conflicts(rel, choice)) == 1 and rc.conflicts(rel, choice)[0].startswith('Game: ')
    assert rc.blocking(rel, choice)
    rc.toggle(rel, choice, TID, 'B', False)
    assert not rc.blocking(rel, choice)


def test_preset_round_trip_drops_unknown_keys():
    rel = phoenix()
    saved = rc.to_preset({TID: {MOD, ADDON}, rc.ORPHANS: set()})
    assert saved == {'0100B7C00933A000': sorted([ADDON, MOD]), '0000000000000000': []}
    saved['0100B7C00933A000'].append('gone')
    assert rc.from_preset(rel, saved)[TID] == {MOD, ADDON}
    assert rc.from_preset(rel, None) == rc.defaults(rel)
    assert rc.from_preset(rel, {'zz': ['x'], '0100B7C00933A000': 'bad'}) == rc.defaults(rel)
