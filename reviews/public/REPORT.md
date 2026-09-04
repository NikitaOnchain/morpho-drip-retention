> Portable copy of the original independent report (Russian). Only local hyperlinks were remapped to final-package counterparts or replaced by explicit omission notices; original line references and RC2 measurements are historical. No verdict, finding or caveat was edited. Original hashes and transformations are in [evidence inventory](evidence_manifest.json). Final-package checks are separate from this review.

# Targeted re-review — DRIP × Morpho RC2 v2

**Вердикт: APPROVE WITH CAVEATS.** Первоначальные R1–R4 закрыты. Пакет пригоден как описательный кейс с воспроизведением опубликованных таблиц/графиков и отдельно проверенным путём от accepted SQLite. Полная публичная воспроизводимость от raw sources не подтверждена и читателю сейчас недоступна; документация это прямо признаёт.

Дата: 2026-09-04. Объект: `release_staging/morpho_rc2_v2`, 170 файлов, 6,084,230 bytes. SHA-256 `release/manifest.json`: `18bedd20ced80d229230214fd1170af1e35063330a017a7e07ca2ea48a99882a`.

Прочитаны первоначальный REPORT (`../REPORT.md`; omitted from public payload, see evidence inventory) и [пакетный RESPONSE_TO_REVIEW](../../docs/RESPONSE_TO_REVIEW.md), затем фактические код, manifests, README и инструкции. Предыдущие и пакетные PASS не принимались за доказательство. Это targeted re-review, не повтор полного независимого ABI/accounting replay из первого ревью и не разрешение на публикацию.

## Статусы замечаний

| Замечание | Прежняя severity | Статус | Проверенный результат |
|---|---|---|---|
| R1 — отсутствуют обязательные producer/evidence и portable provenance | HIGH | **CLOSED** | Зависимости включены; 14 original→derivative пар проверены по обеим сторонам; изменение арифметики producer/reviewer не обнаружено; accepted-SQLite entrypoint успешно исполнен. |
| R2 — 16 broken links в будущем пакете | MEDIUM | **CLOSED** | Все 16 восстановлены; 144 локальные Markdown-ссылки разрешаются внутри самого пакета. |
| R3 — нет CSV-only пути и полных команд/уровней воспроизведения | MEDIUM | **CLOSED** | CSV-only и SQLite-route исполнены; четыре raw CLI-команды успешно разобраны реальными argparse; границы проверенного и непроверенного явно описаны. |
| R4 — два PNG изображают sparse post observations как непрерывную траекторию | MEDIUM | **CLOSED** | Фактически просмотрены оба исправленных PNG: линия останавливается в E, post имеет отдельные подписанные точки и собственную оговорку. |

`CLOSED` у R1/R3 относится к дефектам упаковки, provenance, runnable instructions и честности заявлений. Это **не** статус успешного полного raw rebuild или публичного получения источников. Эти ограничения оценены отдельно ниже; последнее указание пользователя допускает ограниченную воспроизводимость без обязательного расширения работ.

## R1 — зависимости и original→derivative provenance

Независимый inventory совпал с `release/manifest.json`: 168 payload entries плюс сам manifest и SHA256SUMS. Проверены точное множество файлов, размеры и hashes, включая manifest через SHA256SUMS. Нет незаявленных файлов. Все локальные Python imports обеспечены пакетом/stdlib; единственная выявленная сторонняя Python-библиотека — Pillow, закреплённая в `requirements-release.txt`.

У каждой из 14 записей derivative manifest фактический оригинал совпадает с `original_sha256`, пакетный файл — с `release_sha256`. Для семи JSON derivatives список реально изменённых полей в точности совпал с заявленными path transformations. Frozen analysis manifest, пять численных CSV, definitions и production DB identity сохранились. SHA renderer совпал с manifest; его source identity совпал с оригинальным producer.

Просмотрены кодовые diff: у analyzer изменены docstring, разрешение пути metadata относительно package root и системных fonts через WINDIR. У headline reviewer заменён только accepted-artifact hash check на явную проверку provenance. Расчётные функции и SQL не изменены этими исправлениями. Дополнительно проверены 18 provenance cases для producer и двух изменённых PNG: три корректные mappings приняты; отсутствие mapping, неверный original hash, неверный derivative hash, duplicate mapping и повреждённые bytes отвергнуты для каждого из трёх файлов.

**Файлы/строки:** [release/derivative_manifest.json](../../release/derivative_manifest.json):1; [scripts/release_support.py](../../scripts/release_support.py):33; [scripts/review_phase7_headlines.py](../../scripts/review_phase7_headlines.py):69; [scripts/release_routes.py](../../scripts/release_routes.py):71.

**Evidence:** [derivative_verification.json](derivative_verification.json), analyzer diff (`diff_analyze_phase7_metrics.txt`; omitted from public payload, see evidence inventory), reviewer diff (`diff_review_phase7_headlines.txt`; omitted from public payload, see evidence inventory), [contract_checks.json](contract_checks.json), [static_audit.json](static_audit.json).

**Минимальное оставшееся исправление:** для закрытия R1 не требуется. Public source access не становится доступным от наличия hashes; это отдельная принятая оговорка.

## R2 — ссылки внутри конкретного пакета

Проверены все 144 локальные Markdown-ссылки, включая изображения. Каждая цель существует и после разрешения пути остаётся внутри package root. Прежние 16 cases загружены из первоначального review evidence, а не только из списка, поставленного автором RC2. Все разрешаются. Отдельных reference-style/HTML local links поиском не выявлено.

Проверка performed на самом RC2 и его точной копии. Родительский workspace не использовался как fallback. Дополнительно пакетный `audit_release_package.py` завершился exit 0 под reviewer-owned IO guard.

**Файлы/строки:** полный перечень старых/новых locations в local_links.json (`local_links.json`; omitted from public payload, see evidence inventory). В частности: [docs/HEADLINE_PROVENANCE.md](../../docs/HEADLINE_PROVENANCE.md):5,20 и [docs/SOURCES.md](../../docs/SOURCES.md):103,110,114,121,127,140,153,155.

**Evidence:** local_links.json (`local_links.json`; omitted from public payload, see evidence inventory), package_command_receipt.json (`package_command_receipt.json`; omitted from public payload, see evidence inventory), package_before.json (`package_before.json`; omitted from public payload, see evidence inventory).

**Минимальное оставшееся исправление:** не требуется. Проверка наличия file targets не является проверкой внешних HTTP-адресов, GitHub anchors или фактического Markdown rendering.

## R3 — реальные уровни воспроизведения

Все исполняемые команды запускались из `package_copy/`, созданной побайтным копированием RC2. Записи разрешались только в отдельных review-owned outputs; пакет был read-only на уровне Python IO guard. Сеть и дочерние процессы запрещены. Для CSV-run дополнительно запрещены любые SQLite connections. Оригинальный workspace не включён в разрешённые read roots. Для SQLite-run разрешён только специально подготовленный bundle, содержащий два явно перечисленных внешних файла.

Guard — собственный guard_run.py (`guard_run.py`; omitted from public payload, see evidence inventory), не пакетный `run_release_sandbox.py`. Он проверяет нормальные Python file/listing/mutation/SQLite/socket/process operations, но не является OS-level security sandbox. Это достаточная проверка случайных зависимостей для просмотренного кода, не доказательство изоляции произвольного враждебного native-кода.

| Уровень | Реальный результат targeted re-review |
|---|---|
| CSV → figures | Exit 0; 5 CSV; **6/6 PNG побайтно совпали с RC2**. Ноль SQLite connections, сетевых попыток и запрещённых обращений. Ни bundle, ни original workspace не разрешены. |
| Accepted SQLite + Merkl metadata → review/metrics → revised figures | Exit 0 за 78.547 s; 2 external inputs; два подключения только `mode=ro&immutable=1`; 648 metric rows и 10,215 share reconciliations, defects=0. **5/5 CSV и 6/6 PNG совпали** при отдельном сравнении hashes. |
| Missing / wrong bundle | Отсутствующий bundle и неверный DB hash дают явную ошибку до создания job. Обращений к workspace/network вместо недостающих inputs нет. |
| Raw-route CLI completeness | Все четыре полных набора аргументов приняты реальными `parse_args()`. Их `main()` не исполнялись. |
| Raw source identities | Размеры/SHA-256 всех **3,163 external inputs** сверены с имеющимися локальными источниками. Это проверка идентичности имеющейся копии, не испытание получения bundle другим читателем. |

Тестовая среда: Windows, Python 3.12.14, SQLite 3.53.1, Pillow 12.3.0. Использованы существующие Segoe UI fonts, их hashes сохранены. Ничего не устанавливалось. Ограничение exact PNG bytes теми же Pillow/fonts прямо указано в документации; наличие Python-библиотеки `sqlite3` в import не означает чтения DB — CSV-run не открыл ни одного соединения.

SQLite-route действительно требует ровно два внешних файла: accepted production DB (`80aca74c…9543`, 1,878,016,000 bytes) и Merkl snapshot (`4d9bc3e0…e8c7`, 1,236,207 bytes). Они скопированы обычными файлами, без hardlinks. Raw shards и RPC caches в исполняемый metrics bundle не помещались. Оба inputs после запуска сохранили hashes. Producer сначала пересоздаёт исходное представление в disposable job, затем CSV renderer создаёт revised PNG в `work/figures/`; итог проверен именно там, а не по статусу или временным исходным PNG.

Полный независимый пересчёт 1,231,462 событий из первого ревью здесь не повторён. Текущая задача проверяет исполнимость исправленного пакета; запуск авторских producer/reviewer не называется новым независимым accounting replay. Сохранение independently reviewed numerical baseline установлено через совпадение input/output identities и просмотр изменений кода.

**Файлы/строки:** [docs/REPRODUCTION.md](../../docs/REPRODUCTION.md):15,30,44,54,64; [scripts/release_routes.py](../../scripts/release_routes.py):78,90,109; [docs/FULL_RECONSTRUCTION_COMMANDS.md](../../docs/FULL_RECONSTRUCTION_COMMANDS.md):7,19,31,44,59.

**Evidence:** [verification_summary.json](verification_summary.json), CSV guard receipt (`csv_command_receipt.json`; omitted from public payload, see evidence inventory), [CSV QA](csv_qa.json), SQLite guard receipt (`metrics_command_receipt.json`; omitted from public payload, see evidence inventory), [SQLite route QA](sqlite_route_qa.json), [headline review](headline_review.json), external identities (`external_identity_checks.json`; omitted from public payload, see evidence inventory), [CLI/negative cases](contract_checks.json).

**Минимальное оставшееся исправление:** для заявленных проверенных уровней не требуется. Full raw rebuild и логический мост к новой DB нельзя обозначать PASS без их выполнения; сейчас они правильно отмечены как непроведённые.

## R4 — sparse post-period на двух графиках

Фактически просмотрены [active borrowers PNG](../../figures/phase7_active_borrowers.png) и [archetypes PNG](../../figures/phase7_archetype_borrowed_assets.png). В обоих плотная линия заканчивается в E. После E видны только +30/+90/+180 markers, с подписями дат/checkpoints; соединительных post segments нет. Вертикальные reference lines обозначают checkpoints и не изображают временную динамику. На каждом изображении есть самостоятельная оговорка: промежуточная траектория не наблюдалась.

На active-borrower PNG сохранены cross-sectional count, порог на позицию и отдельная shares-only sensitivity. На archetype PNG сохранены native units, отдельные panel scales и нулевые основания. Существенного clipping или наложения подписей при просмотре исходных изображений не обнаружено. Четыре остальные PNG совпадают с первоначальными, обе presentation derivatives воспроизводятся побайтно обоими маршрутами.

**Файлы/строки:** [scripts/release_chart_renderer.py](../../scripts/release_chart_renderer.py):301,308,312,337,339,351,383; [README.md](../../README.md):45,53.

**Evidence:** [visual_review.json](visual_review.json), [PNG hash comparisons](verification_summary.json).

**Минимальное оставшееся исправление:** не требуется. Проверены standalone PNG; browser/GitHub/mobile rendering assembled Markdown **не проводился** и не получает PASS.

## Непроверенный raw rebuild и отсутствие публичного bundle

**Выпуск с явно ограниченной воспроизводимостью допустим.** Читатель, имеющий только release payload и указанные runtime/fonts, может воспроизвести таблицы/графики из включённых CSV. SQLite-level проверен здесь с локально доступными внешними inputs, но читатель без такого bundle выполнить его сейчас не сможет. Полный source-to-new-state-to-metrics путь остаётся непроверенным.

README не обещает готовый публичный source download: [README.md:86](../../README.md) прямо указывает исключённые raw/SQLite/caches, необходимость отдельного checksum-matched bundle и отсутствие download location. [REPRODUCTION.md:30](../../docs/REPRODUCTION.md) говорит, что URL и tested third-party acquisition route отсутствуют, и до получения inputs направляет на CSV-only. [REPRODUCTION.md:64](../../docs/REPRODUCTION.md) явно отделяет непроведённый raw rebuild от tested SQLite-route. Исторические PASS и формулировка про isolated reproduction не подменяют этот предел.

Новый физический SQLite не объявлен автоматически эквивалентным accepted DB: [FULL_RECONSTRUCTION_COMMANDS.md:59](../../docs/FULL_RECONSTRUCTION_COMMANDS.md) требует отдельного logical reconciliation/identity bridge. Его реализации/успешного выполнения в этом re-review не подтверждаю.

| Оставшийся пункт | Статус проверки | Влияние на вердикт |
|---|---|---|
| Full raw → prototype → state rebuild и новая DB → frozen lineage | NOT RUN | Принятое ограничение. Не блокирует описательный v1 с честно ограниченными claims. |
| Получение source bundle публичным/сторонним читателем | OPEN / NOT AVAILABLE | Принятое ограничение для этого вердикта; полноценная публичная source reproduction недоступна. Hash manifest не заменяет доступ. |
| Browser/GitHub/mobile rendering | NOT PERFORMED | Нет визуального signoff assembled Markdown. PNG inspection его не заменяет. |
| Cross-platform/fonts и свежая установка runtime | NOT TESTED | Побайтная воспроизводимость проверена только в записанной Windows-среде. |

Не требуется полный rebuild ради закрытия R1–R4 и не требуется расширение v1 cohorts, USD layer, recipient attribution или causal model. README и reproduction guide уже достаточно ясно ограничивают обещание; обязательного дополнительного текстового исправления не найдено. При публикации эти оговорки должны сохраниться. Проектные source-access/privacy/rendering/publication gates этот review самовольно не закрывает.

## Выполненные и невыполненные проверки

**Выполнены:** чтение initial review/response и изменённого release contract; независимые package hashes/inventory; provenance diffs и негативные тесты; package-local links; Python syntax/import coverage; heuristic paths/secrets/large-file scan; локальная идентичность всех external sources; CSV-only запуск; accepted-SQLite запуск; независимое сравнение всех пяти CSV/шести PNG; raw CLI parse; просмотр двух PNG; контроль неизменности оригиналов/пакета/первоначального review.

**Не выполнены:** полный raw-state rebuild; новый logical DB comparison; повтор исполнения raw-preflight Phase 1/bridge (только CLI parse и input hashes в этом targeted pass); повтор полного independent ABI replay; публичное получение bundle; browser/GitHub/mobile view; внешние HTTP/renderer anchors; cross-platform/fonts; clean dependency installation; dedicated/history/staged secret scanning. Heuristic scan дал ноль hits, но не считается dedicated secret audit. Ни одна из этих непроведённых проверок не обозначена PASS.

Новые RPC/GBA запросы, публикация, push и изменения phase statuses не выполнялись. Все новые файлы находятся только в `reviews/independent/rereview_rc2/`. [unchanged_verification.json](unchanged_verification.json) фиксирует проверку неизменности защищённых источников и пакета. Первоначальный отчёт и его evidence сохранены.

## Собственные scripts и повторение проверки

- check_rc2.py (`check_rc2.py`; omitted from public payload, see evidence inventory): exact inventory, original→derivative comparison, local links, syntax/imports, external identities, безопасные copies и финальный hash check.
- guard_run.py (`guard_run.py`; omitted from public payload, see evidence inventory): собственный IO/network guard с разделёнными read/write roots.
- check_contracts.py (`check_contracts.py`; omitted from public payload, see evidence inventory): provenance/source rejection cases и parse четырёх raw commands.
- summarize_rc2.py (`summarize_rc2.py`; omitted from public payload, see evidence inventory): отдельное сравнение реальных generated bytes и сводка evidence.

Scripts не перезаписывают существующие package/job copies. Для нового повторения скопировать эти четыре scripts в новую соседнюю папку под `reviews/independent/`, использовать те же declared inputs и новые output directories. Фактически исполненные script arguments и runtime записаны в `*_command_receipt.json`; запускаемый script остаётся внутри точной package copy. Для подготовки/завершения применены `python -B check_rc2.py prepare` и `python -B check_rc2.py finish`; полная сверка результатов — `python -B summarize_rc2.py`.

Большие SQLite copies в `source_bundle/` и `metrics_output/` — локальные test inputs, не предлагаемые файлы публичного release. Деталь первичного сбоя настройки собственного harness и его исправления сохранена в harness_notes.json (`harness_notes.json`; omitted from public payload, see evidence inventory); она не является дефектом RC2.
