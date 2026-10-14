"""Release analyser on layouts copied from real releases (names shortened)."""
from src.release_analyzer import analyze, default_choice, parse_7z_listing, parse_package, plan

BASE = 'Game [0100B7C00933A000][v0].nsp'
UPD4 = 'Game [0100B7C00933A800][v262144].nsp'
TID = 0x0100B7C00933A000


def archives(table):
    return lambda path: table.get(path)


def only_game(rel):
    assert len(rel.games) == 1, [g.name for g in rel.games]
    return rel.games[0]


def opt(game, name):
    return next(o for o in game.options if o.name == name)


def test_package_names():
    assert parse_package('a/X [0100F7E00C70F001][v0x10000].nsp').version == 0x10000
    assert parse_package('X [010055D009F79004]v196608].nsp').version == 196608
    p = parse_package('Pokemon Scarlet [DLC Set] [0100A3D008C5D001][v0].nsp')
    assert (p.kind, p.game_tid) == ('dlc', 0x0100A3D008C5C000)
    assert parse_package('Upd [0100A3D008C5C800][v786432].nsp').kind == 'update'
    assert parse_package('Port [01909cd6d76c0000].nsp').kind == 'base'
    assert parse_package('Taiko DLC.nsp').tid is None


def test_base_update_dlc():
    rel = analyze([BASE, 'Game [0100B7C00933A800][v65536].nsp', UPD4,
                   'DLC/Game [0100B7C00933B001][v0].nsp'])
    g = only_game(rel)
    assert g.base.name == BASE and len(g.dlcs) == 1
    p = plan(g, default_choice(g))
    assert [x.name for x in p.packages] == [BASE, UPD4, 'Game [0100B7C00933B001][v0].nsp']


def test_mod_with_own_update_replaces_root_update():
    # Pikmin 4: root update v4, the translation needs v2
    mod = 'Russian Machine Translation (26.03.2025)'
    rel = analyze([BASE, UPD4, f'{mod}/atmosphere/contents/0100B7C00933A000/romfs/a.bin',
                   f'{mod}/Game [0100B7C00933A800][v131072].nsp', f'{mod}/ReadMe_Rus.txt'])
    g = only_game(rel)
    m = opt(g, mod)
    assert m.kind == 'mod' and m.lang == 'ru' and [u.version for u in m.updates] == [131072]
    assert default_choice(g) == {m.key}
    with_mod = plan(g, {m.key})
    assert [x.version for x in with_mod.packages if x.kind == 'update'] == [131072]
    assert with_mod.sd_files[0][2] == 'atmosphere/contents/0100B7C00933A000/romfs/a.bin'
    without = plan(g, set())
    assert [x.version for x in without.packages if x.kind == 'update'] == [262144]
    assert without.sd_files == []


def test_several_mods_none_by_default_and_update_conflict():
    # Star Wars Dark Forces: three mods; Pokemon Z-A: two mods needing different updates
    files = [BASE, UPD4]
    for name, ver in (('Text Mod 1', 65536), ('Voice Mod', 65536), ('HD Textures', 196608)):
        files += [f'{name}/atmosphere/contents/0100B7C00933A000/romfs/{name}.bin',
                  f'{name}/Game [0100B7C00933A800][v{ver}].nsp']
    g = only_game(analyze(files))
    assert default_choice(g) == set()
    same = plan(g, {opt(g, 'Text Mod 1').key, opt(g, 'Voice Mod').key})
    assert same.conflicts == [] and len(same.sd_files) == 2
    clash = plan(g, {opt(g, 'Text Mod 1').key, opt(g, 'HD Textures').key})
    assert clash.conflicts


def test_game_groups_and_shared_mod_folder():
    # Pokemon Scarlet and Violet: a folder per game, one translation folder for both
    mod = 'Russian Machine Translation'
    rel = analyze([
        'Pokemon Scarlet/Pokemon Scarlet [0100A3D008C5C000][v0].nsp',
        'Pokemon Scarlet/Pokemon Scarlet [0100A3D008C5C800][v786432].nsp',
        'Pokemon Violet/Pokemon Violet [01008F6008C5E000][v0].nsp',
        'Pokemon Violet/Pokemon Violet [01008F6008C5E800][v786432].nsp',
        f'{mod}/atmosphere/contents/0100A3D008C5C000/romfs/s.bin',
        f'{mod}/atmosphere/contents/01008F6008C5E000/romfs/v.bin',
        f'{mod}/Pokemon Scarlet [0100A3D008C5C800][v720896].nsp',
        f'{mod}/Pokemon Violet [01008F6008C5E800][v720896].nsp',
    ])
    assert [g.name for g in rel.games] == ['Pokemon Scarlet', 'Pokemon Violet']
    for g, own in zip(rel.games, ('s.bin', 'v.bin')):
        m = opt(g, mod)
        assert [f.rsplit('/', 1)[1] for _, f in m.files] == [own]
        assert [u.game_tid for u in m.updates] == [g.tid]
        assert plan(g, {m.key}).packages[1].version == 720896


def test_port_bare_folder():
    # Def Jam: stub NSP + defjamx/ with the NRO, copied to switch/defjamx/
    g = only_game(analyze(['Def Jam [01909cd6d76c0000].nsp', 'defjamx/defjamx.nro',
                           'defjamx/defjamx_env.txt', 'defjamx/game/assets/a.viv']))
    port = opt(g, 'defjamx')
    assert port.kind == 'port'
    assert sorted(d for _, d in port.files) == [
        'switch/defjamx/defjamx.nro', 'switch/defjamx/defjamx_env.txt', 'switch/defjamx/game/assets/a.viv']
    assert default_choice(g) == {port.key}


def test_port_versioned_folder_and_language_archives():
    # NFS Underground 2: Homebrew (0.5.6)/switch/... + switch.7z + switch_russmod.7z
    data = ['switch/nfsu2x/game/B3/Data/a.bin', 'switch/nfsu2x/game/B3/Data/b.bin']
    rel = analyze(['NFSU2 [03DB1E5631154000][v0].nsp', 'Homebrew (0.5.6)/switch/nfsu2x/nfsu2x.nro',
                   'Homebrew (0.5.6)/switch/nfsu2x/nfsu2x_env.txt', 'switch.7z', 'switch_russmod.7z'],
                  archives({'switch.7z': data, 'switch_russmod.7z': data}))
    g = only_game(rel)
    assert [o.name for o in g.options] == ['Homebrew (0.5.6)', 'switch', 'switch_russmod']
    assert default_choice(g, 'uk') == {'Homebrew (0.5.6)', 'switch.7z'}
    # Russian: its archive writes every file of switch.7z, so switch.7z is not copied first
    assert default_choice(g, 'ru') == {'Homebrew (0.5.6)', 'switch_russmod.7z'}


def test_language_overlay_keeps_the_full_data():
    # Professor Layton: switch.7z has all data, switch_rus.zip replaces part of it
    rel = analyze(['Layton [01d07340e2190000].nsp', 'Homebrew (1.0.4)/switch/layton/layton_nx.nro',
                   'switch.7z', 'switch_rus.zip'],
                  archives({'switch.7z': ['switch/layton/a.png', 'switch/layton/b.png'],
                            'switch_rus.zip': ['switch/layton/a.png']}))
    g = only_game(rel)
    chosen = default_choice(g, 'ru')
    assert chosen == {'Homebrew (1.0.4)', 'switch.7z', 'switch_rus.zip'}
    order = [o.name for o, _, _ in plan(g, chosen).sd_files]
    assert order == ['Homebrew (1.0.4)', 'switch', 'switch_rus']  # the overlay is copied last
    assert default_choice(g, 'uk') == {'Homebrew (1.0.4)', 'switch.7z'}


def test_language_folders():
    # Call of Duty 4 / Simpsons: English version/ and Russian version/
    files = ['CoD4 [01B7F96B70C31000][v0].nsp', 'Homebrew (12.10.2026)/switch/codmw/codmw.nro',
             'English version/switch/codmw/game/en.pak', 'Russian version/switch/codmw/game/ru.pak']
    g = only_game(analyze(files))
    assert default_choice(g, 'uk') == {'Homebrew (12.10.2026)', 'English version'}
    assert default_choice(g, 'ru') == {'Homebrew (12.10.2026)', 'Russian version'}


def test_only_data_is_in_another_language():
    # Silent Hill 2: the port's data exists only as switch_RUSS.7z; it must still be copied
    g = only_game(analyze(['SH2 [057DA68233EAB000][v0].nsp', 'Homebrew (v1)/switch/sh2/sh2.nro', 'switch_RUSS.7z'],
                          archives({'switch_RUSS.7z': ['switch/sh2/data/a.bin']})))
    assert default_choice(g, 'uk') == {'Homebrew (v1)', 'switch_RUSS.7z'}


def test_optional_archive_matched_by_port_folder():
    # Dusk: textures archive has dusk/... at its top, the port folder is dusk/
    g = only_game(analyze(['Dusk [01a43f49196b0000].nsp', 'dusk/dusk.nro', 'Optional HD Textures.7z'],
                          archives({'Optional HD Textures.7z': ['dusk/texture_replacements/UI/a.png']})))
    hd = opt(g, 'Optional HD Textures')
    assert hd.files == [('dusk/texture_replacements/UI/a.png', 'switch/dusk/texture_replacements/UI/a.png')]
    assert hd.key not in default_choice(g)


def test_mod_archive_takes_folder_name_and_update():
    # Omori: Russian Language Mod (5.05.2023)/atmosphere.7z + update NSP beside it
    mod = 'Russian Language Mod (5.05.2023)'
    g = only_game(analyze([BASE, UPD4, f'{mod}/atmosphere.7z', f'{mod}/Game [0100B7C00933A800][v196608].nsp'],
                          archives({f'{mod}/atmosphere.7z': ['atmosphere/contents/0100B7C00933A000/romfs/x']})))
    m = opt(g, mod)
    assert m.archive == f'{mod}/atmosphere.7z' and [u.version for u in m.updates] == [196608]


def test_addon_mods_inherit_the_main_mod_update_and_bare_tid_folders():
    # Phoenix Wright: main mod archive + update, add-on folders below it, <TID>/romfs without atmosphere
    mod = 'Russian Language Mod'
    g = only_game(analyze([
        BASE, UPD4, f'{mod}/atmosphere.zip', f'{mod}/Game [0100B7C00933A800][v131072].nsp',
        f'{mod}/Addon - English Voiceover/atmosphere/contents/0100B7C00933A000/romfs/v.bin',
        f'{mod}/Addon - Unlock/Modified scripts/0100B7C00933A000/romfs/s.bin',
        f'{mod}/Addon - Gamesave/systemdata',
    ], archives({f'{mod}/atmosphere.zip': ['atmosphere/contents/0100B7C00933A000/romfs/t.bin']})))
    addon = opt(g, 'Addon - English Voiceover')
    assert addon.lang == 'en' and [u.version for u in addon.updates] == [131072]
    scripts = opt(g, 'Modified scripts')
    assert scripts.files[0][1] == 'atmosphere/contents/0100B7C00933A000/romfs/s.bin'
    assert [u.version for u in scripts.updates] == [131072]


def test_old_titles_path_and_exefs_nsp_port():
    g = only_game(analyze([BASE, 'Mod/atmosphere/titles/0100B7C00933A000/romfs/a']))
    assert g.options[0].kind == 'mod' and g.options[0].tids == {TID}
    # N.O.V.A. 3: exefs.nsp under atmosphere/contents is an SD file, not a package to install
    g = only_game(analyze(['NOVA [0570F3D9B545F000][v0].nsp',
                           'Homebrew (1.0.1)/atmosphere/contents/0570F3D9B545F000/exefs.nsp',
                           'Homebrew (1.0.1)/switch/nova3/nova3.nro']))
    assert g.options[0].kind == 'port' and len(g.options[0].files) == 2 and len(g.updates + g.dlcs) == 0


def test_mod_for_a_game_not_in_the_release():
    # Metroid Prime: the base is still downloading (.!qB), the mod is complete
    rel = analyze(['Metroid [010012101468C000][v0] (6.76 GB).nsz.!qB',
                   'Russian Language Mod/atmosphere/contents/010012101468C000/romfs/a'])
    g = only_game(rel)
    assert g.base is None and g.name == '010012101468C000'
    assert rel.skipped[0][1] == 'download not finished'


def test_mod_tid_mismatch_is_flagged():
    g = only_game(analyze([BASE, 'Mod/atmosphere/contents/0100000000001000/romfs/a']))
    assert g.options[0].tid_mismatch


def test_several_ports_in_one_folder_are_shared():
    # Donkey Kong Country Trilogy: three stubs and one switch/ with three NRO folders
    rel = analyze(['DKC 1 [03DB1DA917792000][v0].nsp', 'DKC 2 [03DB1CAB43D78000][v0].nsp',
                   'switch/dkc1/dkc1.nro', 'switch/dkc2/dkc2.nro'])
    assert len(rel.games) == 2 and all(not g.options for g in rel.games)
    assert [o.kind for o in rel.orphans] == ['port']


def test_skipped_and_unknown():
    rel = analyze([BASE, 'setup.exe', 'SwitchEmu/Firmware 21.0.0.zip', 'Keys 21.0.0.7z', 'font.zip', 'x.7z', 'Taiko DLC.nsp'],
                  archives({'font.zip': ['pakchunk0-Switch_p.pak'], 'x.7z': ['Game [0100B7C00933A800][v0].nsp']}))
    reasons = dict(rel.skipped)
    assert reasons['setup.exe'] == reasons['Keys 21.0.0.7z'] == 'not for the console'
    assert reasons['font.zip'] == 'unknown layout'
    assert 'extract' in reasons['x.7z']
    assert rel.unknown == ['Taiko DLC.nsp']
    assert analyze(['m.7z'], None).skipped[0][1].startswith('cannot read')


def test_later_option_overwrites_the_same_file():
    rel = analyze(['P [01d07340e2190000].nsp', 'A/switch/p/x.bin', 'B (rus)/switch/p/x.bin'])
    g = only_game(rel)
    sd = plan(g, {o.key for o in g.options}).sd_files
    assert [src for _, src, _ in sd] == ['B (rus)/switch/p/x.bin']


def test_7z_listing_parser():
    text = ('Path = atmosphere\r\nSize = 0\r\nAttributes = D\r\n\r\n'
            'Path = atmosphere\\contents\\0100B7C00933A000\\romfs\\a.bin\r\nSize = 5\r\nAttributes = A\r\n\r\n'
            'Path = dir2\r\nFolder = +\r\n\r\n')
    assert parse_7z_listing(text) == ['atmosphere\\contents\\0100B7C00933A000\\romfs\\a.bin']


def test_mod_still_downloading_is_not_chosen():
    g = only_game(analyze([BASE, 'Mod/atmosphere/contents/0100B7C00933A000/romfs/a',
                           'Mod/atmosphere/contents/0100B7C00933A000/romfs/b.pak.!qB']))
    assert g.options[0].incomplete and default_choice(g) == set()
