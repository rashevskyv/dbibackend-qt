"""
Add dialog for a release with ports, mods or language variants: one block per game,
a tick box per option, pre-ticked by release_choice.defaults. Also used from the queue
row ("Choose release options...") until the game starts.
"""
from html import escape
from typing import Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout
)

from . import release_choice as rc
from .release_analyzer import Option, Release

KEY_ROLE = Qt.ItemDataRole.UserRole
TID_ROLE = Qt.ItemDataRole.UserRole + 1
KIND = {'port': 'Port', 'data': 'Port files', 'mod': 'Mod'}


def _notes(o: Option, rel: Release, tid: int) -> str:
    out = [f'needs update v{u.version >> 16}' for u in o.updates[:1]]
    if o.parent:
        parent = next((x.name for x in rc.options(rel, tid) if x.key == o.parent), o.parent)
        out.append(f'add-on to {parent}')
    if o.tid_mismatch:
        out.append('made for another title ID')
    if o.incomplete:
        out.append('still downloading')
    if o.archive:
        out.append('archive')
    return ', '.join(out)


class ReleaseDialog(QDialog):
    PLAIN = 'plain'
    SMART = 'smart'

    def __init__(self, rel: Release, choice: rc.Choice, title: str, parent=None, allow_plain: bool = True):
        super().__init__(parent)
        self.setWindowTitle('Choose what to install')
        self.setMinimumSize(720, 440)
        self.rel = rel
        self.choice = {tid: set(keys) for tid, keys in choice.items()}
        self.result_mode: Optional[str] = None
        self._sync = False

        layout = QVBoxLayout(self)
        head = QLabel(f"<b>{escape(title)}</b><br>Ticked items go to the console. Games, updates and DLC "
                      "are always installed; ports, translations and mods are copied to the microSD.")
        head.setWordWrap(True)
        layout.addWidget(head)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Item', 'Type', 'Language', 'Notes'])
        self.tree.setRootIsDecorated(False)
        layout.addWidget(self.tree, 1)
        self._fill()
        self.tree.itemChanged.connect(self._on_changed)

        self.warn = QLabel()
        self.warn.setWordWrap(True)
        layout.addWidget(self.warn)

        buttons = QHBoxLayout()
        cancel = QPushButton('Cancel')
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        buttons.addStretch()
        if allow_plain:
            plain = QPushButton('Only packages')
            plain.setToolTip('Add the folder as before: every package, nothing copied to the microSD')
            plain.clicked.connect(lambda: self._done(self.PLAIN))
            buttons.addWidget(plain)
        self.ok = QPushButton('Add' if allow_plain else 'Save')
        self.ok.setDefault(True)
        self.ok.clicked.connect(lambda: self._done(self.SMART))
        buttons.addWidget(self.ok)
        layout.addLayout(buttons)
        self._refresh()

    def _game_header(self, text: str, detail: str):
        item = QTreeWidgetItem(self.tree, [text, '', '', detail])
        item.setToolTip(0, text)
        item.setToolTip(3, detail)
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)

    def _option_row(self, o: Option, tid: int):
        name = f'    {o.name}' if not o.parent else f'        {o.name}'
        item = QTreeWidgetItem(self.tree, [name, KIND[o.kind], o.lang or '', _notes(o, self.rel, tid)])
        item.setData(0, KEY_ROLE, o.key)
        item.setData(0, TID_ROLE, tid)
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
        if o.incomplete:
            flags = Qt.ItemFlag.ItemIsUserCheckable   # greyed: cannot be installed until the download ends
        item.setFlags(flags)
        item.setToolTip(0, f'{o.name}\n{o.key}\n{len(o.files)} file(s)')
        item.setToolTip(3, item.text(3))

    def _fill(self):
        for g in self.rel.games:
            parts = []
            if g.base:
                parts.append('game')
            if g.updates:
                parts.append(f'update v{g.updates[-1].version >> 16}')
            if g.dlcs:
                parts.append(f'{len(g.dlcs)} DLC')
            self._game_header(f'{g.name}  [{g.tid:016X}]', ', '.join(parts) or 'mods only')
            for o in g.options:
                self._option_row(o, g.tid)
        if self.rel.orphans:
            self._game_header('For any game of this release', 'copied once to the microSD')
            for o in self.rel.orphans:
                self._option_row(o, rc.ORPHANS)
        for u in self.rel.unknown:
            QTreeWidgetItem(self.tree, [f'    {u}', 'Package', '', 'no title ID in the name: the console reads it'])
        for c in range(4):
            self.tree.resizeColumnToContents(c)
        self.tree.setColumnWidth(0, min(self.tree.columnWidth(0), 420))   # long names: tooltip, notes stay visible

    def _refresh(self):
        self._sync = True
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            key = item.data(0, KEY_ROLE)
            if key is None:
                continue
            on = key in self.choice.get(item.data(0, TID_ROLE), set())
            item.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self._sync = False
        problems = rc.conflicts(self.rel, self.choice)
        sd = rc.sd_file_count(self.rel, self.choice)
        lines = [f'{sd} file(s) to the microSD.'] + [f"<span style='color:#e0a000'>⚠ {escape(p)}</span>" for p in problems]
        self.warn.setText('<br>'.join(lines))
        stop = rc.blocking(self.rel, self.choice)
        self.ok.setEnabled(not stop)
        self.ok.setToolTip('Untick one of the mods that need different updates, or a download that is not finished' if stop else '')

    def _on_changed(self, item: QTreeWidgetItem, column: int):
        if self._sync or column != 0 or item.data(0, KEY_ROLE) is None:
            return
        rc.toggle(self.rel, self.choice, item.data(0, TID_ROLE), item.data(0, KEY_ROLE),
                  item.checkState(0) == Qt.CheckState.Checked)
        self._refresh()

    def _done(self, mode: str):
        self.result_mode = mode
        self.accept()

    @classmethod
    def ask(cls, rel: Release, choice: rc.Choice, title: str, parent=None,
            allow_plain: bool = True) -> Tuple[Optional[str], rc.Choice]:
        dlg = cls(rel, choice, title, parent, allow_plain)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg.result_mode, dlg.choice
        return None, choice
