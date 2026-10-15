# Walkthrough

Журнал змін за версіями, найновіші зверху. Поточна версія — **2.9.10**. Усі зміни перевірені лише локально (pytest, `compileall`); на фізичному Switch нічого не перевірено.

## 2.9.10 — release dialog: choose ports, translations and mods per game

- **Add dialog:** a dropped folder with ports, port files or mods opens "Choose what to install" instead of the folder-mode question: one block per game, a tick box per option, pre-ticked by `default_choice` in the PC's UI language. Shared ports (Donkey Kong Country `switch/dkc1..3`) are all ticked; the user unticks. Ticking an add-on ticks its mod; unticking a mod drops its add-ons. Conflicts (two mods that need different updates, a mod for another title ID) are shown under the list. "Only packages" adds the folder the old way. A folder with only packages still gets the old question.
- **Queue row:** the folder holds the packages the choice needs (a mod's own update replaces the newer one). "Choose What to Install..." in the row's menu changes it until a package of the folder starts.
- **Presets and resume:** `releases` maps each release folder to its choice per title ID; on load the folder is analysed again and unknown keys are dropped.
- **Analyser:** an option named "Update"/"Updated" (Simpsons "Homebrew Update (v0.6.1)") is ticked and copied after the port files; before, the older English archive dropped it.
- Not yet: the files for the microSD are not sent (phase 3). The log shows how many there would be.
- Verification: pytest 131 passed (new `test_release_choice.py`, `test_release_queue.py`). Dialog rendered for 13 real releases. Scan of 129 releases: only Simpsons changed.

## 2.9.9 — analyser: mod add-ons, file replacements, homebrew stubs

- **Add-ons:** a mod in a folder below another mod (Phoenix Wright "Addon - ...") gets `parent`. Add-ons are off by default, are copied after their mod, and `plan()` reports an add-on chosen without its mod.
- **Replacement files:** an archive of bare files whose names match files of the mod beside it is an add-on that replaces them (DQ XI `better_russian_font_pakchunk0-Switch_p.pak_duckbill.zip` → the mod's `romfs/JackGame/Content/Paks/pakchunk0-Switch_p.pak`). Before, it was skipped as an unknown layout.
- **Homebrew stub TIDs:** a title ID ending outside 000/800/001–7FF is a base (Simpsons Russian stub `...6d99` was read as a DLC).
- **Port files named "... Mod"** (Simpsons voice mods) follow the mod rule: on only when there is one.
- **Ports:** an `.nro` counts only under `switch/`; the `.nro` modules in Yakuza Kiwami's romfs made its mod a port.
- **Several ports in one `switch/`** (Donkey Kong Country 1–3): one shared option per `switch/<port>/` folder.
- Verification: pytest 121 passed. Scan of 113 releases: only the cases above changed.

## 2.9.8 — analyser defaults: mismatched and downloading mods

- A lone mod made for a title ID that is not in the release is no longer chosen by default; `plan()` reports it as a conflict to confirm. A chosen option with a file still downloading is a conflict too.
- A file still downloading marks only its own folder unit. Before, a `.!qB` at the release root marked every root-level option (port data, `switch.7z`) as incomplete.
- Verification: pytest 119 passed (2 new tests). Scan of 113 releases: the only change is Metroid Prime's mod, now marked incomplete.

## 2.9.7 — release analyser (phase 1 of smart release install)

- **New `src/release_analyzer.py`** (pure logic, no Qt, not wired into the UI yet): reads a dropped folder or archive and finds games (base, updates, DLC joined by the title ID in the file name), ports (NRO folders, `switch/` trees), port data (`switch.7z`, `English version/`, `Russian ROM.7z`), LayeredFS mods (`atmosphere/contents|titles/<TID>`, bare `<TID>/romfs`), and what to skip (emulators, firmware, keys, `.exe`, unfinished downloads, unknown archives).
- **Mod update rule:** an update NSP in a mod folder belongs to that mod and to add-on mods below it. With the mod chosen, `plan()` installs that update instead of the release's newer one; two chosen mods that need different updates are a conflict.
- **Defaults (`default_choice`)**, used by MTP later and to pre-tick the dialog: port files without a language, plus the UI language, else English; a port's only data is kept even in another language; "Optional" archives are off; a mod is on only when the game has exactly one.
- Archives are listed with 7-Zip (`7z l -slt`); without 7-Zip they are reported as unreadable.
- CLI for checking real releases: `python -m src.release_analyzer <folder>` (`HUB_LANG=uk|ru|en`).
- Verification: pytest 118 passed (21 new in `tests/test_release_analyzer.py`, layouts copied from real releases). All 113 releases in `D:\Downloads\switch` scanned with no error; open cases: Donkey Kong Country Trilogy (3 ports in one `switch/`) goes to shared files, Dragon Quest XI font `.pak` zip has no SD path.

## 2.9.6 — overall total ignores header reads of unticked files

- `src/usb_handler.py`: the console reads headers of every listed file to plan the queue; reads of unticked files no longer add to the overall install total. Test: `tests/test_usb_range.py::test_header_read_of_unticked_file_keeps_overall_total`.

## 2.9.5 — install queue: drag rows, sort by column header

- **Row drag (`src/widgets.py`, `src/tree_item_builder.py`):** press and move on a queue row (name, size, target, status or path cell) and the row moves to the drop point. The drag handle still works. Rows that are installing or done, and conflict rows, do not drag. Ctrl or Shift click keeps the normal selection. A small move under the drag threshold stays a click and does not start a rubber-band selection.
- **Drop line:** a blue line marks where the dragged row lands. It hides after drop or cancel.
- **Header sort (`src/file_operations.py`, `src/ui_manager.py`, `src/queue_manager.py`, `src/queue_reorder.py`):** click Name, Size, Target, Status or Path to sort the install queue. Click again to reverse. Installing and installed rows keep their places. Folder children sort inside their folder. A running USB session gets the new order. The select-all column does not sort.
- **Fix:** the drag handle set no MIME data, so `QDrag.exec()` returned at once and nothing moved.
- **Removed:** the tree's own automatic sort (`FileTreeWidgetItem.__lt__`). The tree order is the install queue.
- Verification: pytest 96 passed (88 before; 8 new in `tests/test_sort_and_drag_handle.py`, mouse events sent to the tree viewport). exe built with PyInstaller (`dbibackend.spec`), bundled `src` checked for the new code; not launched on this PC (a 2.9.4 instance was running). On the PC with a real mouse: drag a row by its name, click each header twice, check Set as Next.

## 2.9.4 — проекція накопичувачів Sphaira, живий план черги, звіт сесії та відновлення

- **3 метрики сховища як у Sphaira (`src/storage_widget.py`):** під час передачі/встановлення замість одного лише `+focus` тепер відображаються всі три метрики одночасно у форматі Sphaira: `+<written> / <package_size> / <free_space>` (наприклад, `+128.8 MB / 162.5 MB / 7.4 GB`). У спокійному стані відображається обсяг вільного місця. Ширину лейбла значення тепер розраховує `QFontMetrics.horizontalAdvance`, що виключає накладання або обрізання тексту, а мінімальну ширину віджета встановлено у 280 пікселів.
- **Дія "Set as Next in Queue" у контекстному меню (`src/main_window.py`, `src/queue_manager.py`, `src/queue_reorder.py`, `src/file_operations.py`):** у контекстне меню кожної гри та папки додано пункт `Set as Next in Queue` («поставити наступним в чергу»). Вибрані елементи акуратно переміщуються безпосередньо після активних та завершених ігор із захистом активного префіксу, автоматично оновлюють UI та надсилають оновлений список у живу USB-чергу SPHQ.
- **Синхронізація плану черги та проекція накопичувачів (`src/dbi_protocol.py`, `src/session_coordinator.py`, `src/storage_widget.py`):** додано обробку `CMD_ID_QUEUE_PLAN`. Консоль надсилає свій розрахований план черги (вибір, реальний накопичувач для Auto-пакунків, фактичний розмір інсталяції, прапорці стану, наявність базової гри). ПК відображає реальний диск у комбобоксі (`Auto → SD` або `Auto → NAND`), синхронізує зняті на консолі галочки, а смуги сховища будують проєкцію планованого заповнення (SetStorageProjection) з підсвічуванням рядка під курсором миші. Неможливі цільові накопичувачі скидаються в Auto.
- **Закріплений плаваючий банер (`src/widgets.py`):** коли встановлюваний пакунок виходить за межі видимості при скролі довгої черги, вгорі таблиці відображається закріплений банер із назвою, цільовим диском і градієнтним прогресом. Клік повертає список до активного елемента.
- **Атомарне автозбереження та відновлення сесії (`src/preset_manager.py`, `src/main_window.py`):** черга передачі атомарно фіксується у `resume.dbi`. При запуску після збою чи вимкнення пропонується продовжити незавершені файли в один клік.
- **Звіт сесії та розшифровка помилок (`src/session_report.py`, `src/session_coordinator.py`):** після сесії формується текстовий звіт у `reports/` з класифікацією встановлених/пропущених/неуспішних ігор, аналізом оновлень і DLC без базової гри та перекладом числових кодів модулів 505 (Sphaira) і Horizon зрозумілою мовою.
- **Захист автогібернації (`src/hibernation.py`, `src/main_window.py`):** перевірка активності вводу Windows (`GetLastInputInfo`). Якщо користувач за ПК, гібернація не запускає зворотний відлік без відома людини; якщо ПК вільний — 3-хвилинний відлік і миготіння в панелі завдань.
- **Політика для вже встановлених пакунків:** вибір режиму (`Console setting`, `Reinstall`, `Skip`, `Prompt`) у статусній панелі, що передається в заголовку SPHQ.

## 2.9.3 — консоль у MTP: бекенд просить Kefir Hub перейти в PC Install (USB)

- **`src/mtp_marker.py` (новий):** MTP (VID 057E / PID 201D) і USB-лінк встановлення (PID 3000) — різні USB-пристрої, тож консоль у режимі MTP не бачить USB-сервер. Коли сервер запущено (кнопкою або автостартом) і він ще чекає консоль, а консоль видно як MTP, бекенд один раз записує файл `kefir-hub.pc-install` у корінь сховища `microSD card` (або першого доступного) через Shell COM/WPD у PowerShell (`-EncodedCommand`, окремий `QThread`). Kefir Hub 0.14.038+ на цей файл питає «A PC install app is waiting. Stop MTP and open PC Install (USB)?», сам видаляє файл, зупиняє MTP і відкриває лінк; сервер підключається звичайним циклом повторів. Повторний запис лише після того, як консоль вийшла з MTP і повернулась (відповідь «No» не дає спаму). Лише Windows; у журналі — `asked Kefir Hub to switch…` або причина відмови.
- **`src/usb_driver.py`:** `switch_present(backends, pid=...)` перевіряє й інший PID; `src/server_operations.py`: рішення в `check_connection()` (кожні 2 с), 3 тести в `tests/test_mtp_marker.py`.
- Перевірено лише локально: pytest 88, запуск скрипта без консолі дає чисту відмову. На консолі: кабель у MTP, запустити USB-сервер → на консолі з'являється запит; «PC Install (USB)» → сервер підключається; «No» → MTP лишається, повторного запиту немає.

## 2.9.1 — виправлення після рев'ю 2.9.0

- `src/usb_handler.py`: поки консоль видно без драйвера, ліміт 30 спроб не витрачається — сервер не зупиняється, доки людина проходить UAC і встановлення.
- `src/usb_driver.py`: інсталятор передається в PowerShell через `-EncodedCommand`, а не шляхом до `.ps1`, тож файл не можна підмінити до запуску з правами адміністратора; лог читається як `utf-8-sig` (без BOM у тексті помилки).

## 2.9.0 — USB без Zadig

- **libusb-1.0 у комплекті** (`libusb-package`): раніше pyusb знаходив лише `libusb0.dll`, яку Zadig кладе в System32, тож на чистому ПК бекенд не мав жодного USB-бекенда.
- **`src/usb_driver.py`**: `find_and_reset_switch()` пробує спершу вбудований libusb-1.0 (WinUSB, libusbK), потім системний (libusb0). Консоль без драйвера дає `NotImplementedError` → `no_driver`; відмова в доступі в Linux (errno 13) → `no_access`.
- **Windows**: `src/install_winusb.ps1` генерує INF для вбудованого `winusb.sys`, каталог (`New-FileCatalog`), підписує його новим самопідписаним сертифікатом, довіреним лише на цьому ПК (приватний ключ видаляється одразу), і ставить пакет через `pnputil /add-driver /install`. Запуск — через UAC (`ShellExecuteEx runas`), окремий потік, помилки — у `%TEMP%\dbi-winusb-install.log`. Механізм той самий, що в Zadig/libwdi, але без WDK.
- **Коли пропонується**: при старті, якщо реєстр (`Enum\USB\VID_057E&PID_3000`) показує консоль без WinUSB/libusbK/libusb0; при підключенні, якщо libusb каже `no_driver`; вручну — Help > Install USB Driver. Наявний драйвер Zadig не чіпається.
- **Linux**: правило udev `/etc/udev/rules.d/99-nintendo-switch-dbi.rules` через `pkexec`. macOS — нічого.
- **Kefir Hub не змінено**: MS OS 2.0 дескриптори вимагають відповіді на vendor-запит до пристрою, а libnx `usb:ds` віддає застосунку лише запити до інтерфейсу.

## 2.8.5 — виправлення після аудиту 2.8.4

- `src/usb_handler.py`: `deque(maxlen=60)` обмежував вікно швидкості ~0.6–2 с замість 30 с. `maxlen` знято; додано `test_speed_window_is_time_bounded`.
- `src/ui_manager.py`: застарілий `switch_storage_label` тепер `hide()` замість шрифту 1px, що лишав піксель біля смуг.
- Тест подвійного ETA перевіряє точний рядок `ETA: 0m 51s / 6m 49s`.

## 2.8.4 — смуги сховища, ETA, Target

- **Target:** текст клітинки порожній (`setText(3, "")`), ціль зберігається в `UserRole`; QComboBox більше не накладається на текст делегата. Стрілку `::down-arrow` стилізовано в обох темах.
- **Відступи:** `QGroupBox` `padding-top: 4px; margin-top: 0.8em`, відступи шапки File Queue `(8, 4, 8, 4)`.
- **Смуги сховища:** `SwitchStorageWidget` (NAND і microSD) за `draw_storage_bar` зі Sphaira: ≤75% зелений, 75–90% бурштиновий, >90% червоний, жовтий сегмент встановлюваного пакунка.
- **ETA:** `format_sphaira_eta()` (`Xh Ym` / `Xm Ys`), подвійний ETA `файл / черга`, швидкість — ковзне вікно 30 с у `USBHandler`.

## 2.8.3 — прогрес у Target

Target не перекриває прогрес рядка. Повторний metadata FileRange не скидає Done. Унікальні USB-байти рахуються по діапазонах без подвоєння.

## 2.8.2 — керування чергою

- Move Up/Down замінено на drag handle; Alt+Up/Down діє з тим самим захистом активних і завершених рядків.
- Select-all — у заголовку таблиці, місце SD/NAND — у верхній смузі File Queue.
- Sphaira v0.13.901 опитує живу чергу між FileRange читаннями.

## 2.8.1 — автогібернація

ПК гібернується після 5 хв без обміну між Switch і сервером (раніше — при зупинці сервера, що не спрацьовувало без `CMD_ID_EXIT`).

- Активність фіксують `usb_handler.py` (заголовки DBI0 і блоки даних) та HTTP/FTP-обробники; `ServerManager` має `get_inactivity_seconds()`, `snooze_inactivity()`, `reset_inactivity()`.
- `MainWindow` перевіряє поріг 300 с щосекунди й показує 30-секундний відлік із «Cancel Hibernation»; відновлення активності скасовує відлік.
- Ручний «Stop Server» скидає таймер. Перед `shutdown /h` сервери зупиняються коректно.

## Раніше (28.09.2026)

- **Папки:** розкривні рядки, пакетний вибір режиму додавання, єдиний шлях `FileManager.ingest_paths()` для кнопок, drag-and-drop і аргументів. Однакові basename з різних шляхів — конфлікт, виключаються з передачі.
- **Рефакторинг:** `ServerManager` розділено на `server_operations.py` (сервери) і `session_coordinator.py` (стан сесії).
- **Sphaira v0.13.899:** жива USB-черга — SPHQ з порядком і ревізією, додавання/вилучення майбутніх файлів, зміна цілі, ACK ревізії.
- **Sphaira v0.13.898:** порожня черга передається маркером `::SPHQ::\n`; legacy DBI/SPHA лишаються з нульовою відповіддю.
- **Sphaira v0.13.897:** відновлено початковий List/SPHQ request (коміт `44348d50`).
