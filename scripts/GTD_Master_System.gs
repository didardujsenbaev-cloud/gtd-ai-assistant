/**
 * GTD MASTER SYSTEM — Google Apps Script
 * ───────────────────────────────────────
 * Запускай в: Extensions → Apps Script → Run → createGTDMasterSystem
 *
 * Что создаёт:
 *   1. 📥 INBOX
 *   2. 🗂 PROJECTS
 *   3. ⚡ NEXT ACTIONS
 *   4. ⏳ WAITING FOR  (авто-фильтр из Next Actions)
 *   5. 💭 SOMEDAY
 *   6. 🎯 AREAS        (заполнен 16 областями)
 *   7. 📊 WEEKLY REVIEW
 *   + Валидация данных, условное форматирование, фиксация строк, ширины колонок
 */

// ─── КОНСТАНТЫ ────────────────────────────────────────────────────────────────

var CONTEXTS = [
  "@Computer","@Phone","@WhatsApp","@Email","@Google Drive","@Cursor","@AI",
  "@SendPulse","@Binotel","@Google Sheets","@Google Docs","@Government",
  "@Contractors","@Team","@Finance","@Legal","@Marketing","@Sales",
  "@Almaty","@Astana","@Shymkent","@Office","@Home","@Garage",
  "@Waiting","@Errands","@Travel","@Agenda","@Deep Work"
];

var AREAS = [
  "Business","Finance","Investments","Family","Health","Learning",
  "Coaching","Real Estate","Visas","Legalization","Marketing","Sales",
  "Operations","IT","Automation","Knowledge Base"
];

var GOOGLE_ACCOUNTS = [
  "Master (Личный)","Google: Узаконение","Google: Визы",
  "Google: Коучинг","Google: Сотрудники"
];

var ACTION_STATUSES  = ["Inbox","Next","Waiting","Done","Cancelled"];
var PROJECT_STATUSES = ["Активен","На паузе","Завершён","Отменён","Someday"];
var SOMEDAY_STATUSES = ["Ожидает","Активирован","Удалён"];
var PRIORITIES       = ["Высокий","Средний","Низкий"];
var HORIZONS         = ["H0","H1","H2","H3","H4","H5"];
var ENERGY_LEVELS    = ["Низкая","Средняя","Высокая"];
var INBOX_SOURCES    = ["WhatsApp","Email","Звонок","Мысль","Встреча","Telegram","Другое"];
var INBOX_RESULTS    = ["Action","Project","Someday","Reference","Trash"];
var INBOX_STATUSES   = ["Новый","В обработке","Обработан","Удалён"];
var DOC_TYPES        = ["SOP","Шаблон","Отчёт","Договор","Чеклист","Справка","Другое"];

var HEADER_BG    = "#1a1a2e";
var HEADER_FG    = "#ffffff";
var ROW_ALT_BG   = "#f8f9fa";
var DONE_FG      = "#9e9e9e";
var OVERDUE_BG   = "#fce4e4";
var WARNING_BG   = "#fff8e1";
var ACCENT_BG    = "#e3f2fd";

// ─── ГЛАВНАЯ ФУНКЦИЯ ──────────────────────────────────────────────────────────

function createGTDMasterSystem() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  ss.setName("GTD Master System");

  var OUR_SHEETS = [
    "📥 INBOX", "🗂 PROJECTS", "⚡ NEXT ACTIONS",
    "⏳ WAITING FOR", "💭 SOMEDAY", "🎯 AREAS", "📊 WEEKLY REVIEW"
  ];

  // Шаг 1: создать все нужные листы (если ещё нет)
  for (var i = 0; i < OUR_SHEETS.length; i++) {
    if (!ss.getSheetByName(OUR_SHEETS[i])) {
      ss.insertSheet(OUR_SHEETS[i]);
    }
  }
  SpreadsheetApp.flush();

  // Шаг 2: удалить посторонние листы (Sheet1, Лист1 и т.п.)
  var allSheets = ss.getSheets();
  for (var i = 0; i < allSheets.length; i++) {
    var name = allSheets[i].getName();
    var isOurs = false;
    for (var j = 0; j < OUR_SHEETS.length; j++) {
      if (name === OUR_SHEETS[j]) { isOurs = true; break; }
    }
    if (!isOurs && ss.getSheets().length > 1) {
      try { ss.deleteSheet(allSheets[i]); } catch(e) {}
    }
  }
  SpreadsheetApp.flush();

  // Шаг 3: получить свежие ссылки на листы
  var sheetInbox   = ss.getSheetByName("📥 INBOX");
  var sheetProj    = ss.getSheetByName("🗂 PROJECTS");
  var sheetActions = ss.getSheetByName("⚡ NEXT ACTIONS");
  var sheetWaiting = ss.getSheetByName("⏳ WAITING FOR");
  var sheetSomeday = ss.getSheetByName("💭 SOMEDAY");
  var sheetAreas   = ss.getSheetByName("🎯 AREAS");
  var sheetReview  = ss.getSheetByName("📊 WEEKLY REVIEW");

  // Установить цвета вкладок
  sheetInbox.setTabColor("#E8A838");
  sheetProj.setTabColor("#4B91F7");
  sheetActions.setTabColor("#4BB543");
  sheetWaiting.setTabColor("#A678E8");
  sheetSomeday.setTabColor("#7E8EAA");
  sheetAreas.setTabColor("#E85D5D");
  sheetReview.setTabColor("#4BB543");

  // Очистить содержимое перед заполнением
  sheetInbox.clearContents();   sheetInbox.clearFormats();   sheetInbox.setConditionalFormatRules([]);
  sheetProj.clearContents();    sheetProj.clearFormats();    sheetProj.setConditionalFormatRules([]);
  sheetActions.clearContents(); sheetActions.clearFormats(); sheetActions.setConditionalFormatRules([]);
  sheetWaiting.clearContents(); sheetWaiting.clearFormats(); sheetWaiting.setConditionalFormatRules([]);
  sheetSomeday.clearContents(); sheetSomeday.clearFormats(); sheetSomeday.setConditionalFormatRules([]);
  sheetAreas.clearContents();   sheetAreas.clearFormats();   sheetAreas.setConditionalFormatRules([]);
  sheetReview.clearContents();  sheetReview.clearFormats();  sheetReview.setConditionalFormatRules([]);
  SpreadsheetApp.flush();

  // Шаг 4: заполнить каждый лист
  _buildInbox(sheetInbox);       SpreadsheetApp.flush();
  _buildProjects(sheetProj);     SpreadsheetApp.flush();
  _buildNextActions(sheetActions); SpreadsheetApp.flush();
  _buildWaitingFor(sheetWaiting, sheetActions); SpreadsheetApp.flush();
  _buildSomeday(sheetSomeday);   SpreadsheetApp.flush();
  _buildAreas(sheetAreas);       SpreadsheetApp.flush();
  _buildWeeklyReview(sheetReview); SpreadsheetApp.flush();

  ss.setActiveSheet(sheetInbox);

  SpreadsheetApp.getUi().alert(
    "✅ GTD Master System создан!\n\n" +
    "7 листов готовы:\n" +
    "📥 INBOX\n🗂 PROJECTS\n⚡ NEXT ACTIONS\n⏳ WAITING FOR\n💭 SOMEDAY\n🎯 AREAS\n📊 WEEKLY REVIEW\n\n" +
    "Начни с листа AREAS — проверь области.\n" +
    "Затем добавь первые проекты в PROJECTS."
  );
}

// ─── INBOX ────────────────────────────────────────────────────────────────────

function _buildInbox(sheet) {
  var headers = [
    "ID","Дата захвата","Содержимое","Источник",
    "Статус","Результат","Создана запись","Обработан"
  ];
  var widths = [80, 110, 400, 110, 110, 100, 120, 110];

  _writeHeaders(sheet, headers, widths);
  _freezeAndResize(sheet, 1, headers.length);

  // Data Validation
  _setDropdown(sheet, "D2:D1000", INBOX_SOURCES);
  _setDropdown(sheet, "E2:E1000", INBOX_STATUSES);
  _setDropdown(sheet, "F2:F1000", INBOX_RESULTS);

  // Авто-ID формула в A2
  sheet.getRange("A2").setFormula('=IF(B2<>"","INB-"&TEXT(ROW()-1,"000"),"")');
  sheet.getRange("B2").setFormula('=IF(C2<>"",TODAY(),"")');

  // Условное форматирование: Обработан = серый
  var rule1 = SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$E2="Обработан"')
    .setFontColor(DONE_FG)
    .setRanges([sheet.getRange("A2:H1000")])
    .build();
  // Удалён = зачёркнутый
  var rule2 = SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$E2="Удалён"')
    .setFontColor("#cccccc")
    .setStrikethrough(true)
    .setRanges([sheet.getRange("A2:H1000")])
    .build();
  // Новый = подсветка
  var rule3 = SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$E2="Новый"')
    .setBackground(ACCENT_BG)
    .setRanges([sheet.getRange("A2:H1000")])
    .build();

  sheet.setConditionalFormatRules([rule3, rule1, rule2]);

  // Пример строки
  var ex = sheet.getRange("A3:H3");
  ex.setValues([[
    "INB-001",
    Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd"),
    "Пример: Позвонить клиенту по объекту на Абая 15",
    "WhatsApp","Новый","","",""
  ]]);
  ex.setBackground("#fffde7");
  sheet.getRange("H3").setNote("Пример — удали эту строку");
}

// ─── PROJECTS ─────────────────────────────────────────────────────────────────

function _buildProjects(sheet) {
  var headers = [
    "ID","Название проекта","Желаемый результат","Область (Area)",
    "Бизнес-аккаунт","Ответственный","Статус","Приоритет",
    "Срок","Следующее действие","Горизонт","Родительский проект",
    "Google Drive (папка)","Заметки","Создан","Обновлён"
  ];
  var widths = [85,280,300,130,150,130,100,90,100,150,70,130,200,200,100,100];

  _writeHeaders(sheet, headers, widths);
  _freezeAndResize(sheet, 1, headers.length);

  // Validation
  _setDropdown(sheet, "D2:D1000", AREAS);
  _setDropdown(sheet, "E2:E1000", GOOGLE_ACCOUNTS);
  _setDropdown(sheet, "G2:G1000", PROJECT_STATUSES);
  _setDropdown(sheet, "H2:H1000", PRIORITIES);
  _setDropdown(sheet, "K2:K1000", HORIZONS);

  // Авто-ID
  sheet.getRange("A2").setFormula('=IF(B2<>"","PRJ-"&TEXT(ROW()-1,"000"),"")');

  // Условное форматирование
  var rules = [];
  // Завершён — серый
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$G2="Завершён"')
    .setFontColor(DONE_FG).setStrikethrough(true)
    .setRanges([sheet.getRange("A2:P1000")]).build());
  // Просрочен + активен — красный
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=AND($G2="Активен",$I2<TODAY(),$I2<>"")')
    .setBackground(OVERDUE_BG)
    .setRanges([sheet.getRange("A2:P1000")]).build());
  // Активен без Next Action — жёлтый
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=AND($G2="Активен",$J2="")')
    .setBackground(WARNING_BG)
    .setRanges([sheet.getRange("A2:P1000")]).build());
  // Высокий приоритет — синий акцент
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=AND($G2="Активен",$H2="Высокий")')
    .setBackground(ACCENT_BG)
    .setRanges([sheet.getRange("A2:P1000")]).build());

  sheet.setConditionalFormatRules(rules);

  // Пример
  var today = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd");
  sheet.getRange("A3:P3").setValues([[
    "PRJ-001","Узаконить объект ул. Абая 15","Получен акт ввода в эксплуатацию",
    "Legalization","Google: Узаконение","Вы","Активен","Высокий",
    "","Позвонить в БТИ","H1","","","Пример — замени на свой",today,today
  ]]);
  sheet.getRange("A3:P3").setBackground("#fffde7");
  sheet.getRange("P3").setNote("Пример — удали эту строку");
}

// ─── NEXT ACTIONS ─────────────────────────────────────────────────────────────

function _buildNextActions(sheet) {
  var headers = [
    "ID","Действие","Проект (ID)","Область (Area)",
    "Контекст","Статус","Приоритет","Энергия",
    "Время (мин)","Срок","Кому делегировано","Ждём от",
    "Ждём с","Заметки","Создано","Выполнено"
  ];
  var widths = [85,320,100,130,120,90,90,90,90,100,140,140,100,200,100,100];

  _writeHeaders(sheet, headers, widths);
  _freezeAndResize(sheet, 1, headers.length);

  // Validation
  _setDropdown(sheet, "D2:D1000", AREAS);
  _setDropdown(sheet, "E2:E1000", CONTEXTS);
  _setDropdown(sheet, "F2:F1000", ACTION_STATUSES);
  _setDropdown(sheet, "G2:G1000", PRIORITIES);
  _setDropdown(sheet, "H2:H1000", ENERGY_LEVELS);

  // Авто-ID
  sheet.getRange("A2").setFormula('=IF(B2<>"","ACT-"&TEXT(ROW()-1,"000"),"")');

  // Условное форматирование
  var rules = [];
  // Done — серый зачёркнутый
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$F2="Done"')
    .setFontColor(DONE_FG).setStrikethrough(true)
    .setRanges([sheet.getRange("A2:P1000")]).build());
  // Cancelled — светло-серый зачёркнутый
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$F2="Cancelled"')
    .setFontColor("#cccccc").setStrikethrough(true)
    .setRanges([sheet.getRange("A2:P1000")]).build());
  // Просрочено — красный
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=AND($F2<>"Done",$F2<>"Cancelled",$J2<TODAY(),$J2<>"")')
    .setBackground(OVERDUE_BG)
    .setRanges([sheet.getRange("A2:P1000")]).build());
  // Waiting — фиолетовый фон
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$F2="Waiting"')
    .setBackground("#f3e5f5")
    .setRanges([sheet.getRange("A2:P1000")]).build());
  // Высокий приоритет Next — синий
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=AND($F2="Next",$G2="Высокий")')
    .setBackground(ACCENT_BG)
    .setRanges([sheet.getRange("A2:P1000")]).build());

  sheet.setConditionalFormatRules(rules);

  // Пример
  var today = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd");
  sheet.getRange("A3:P3").setValues([[
    "ACT-001","Позвонить в БТИ по техпаспорту объекта Абая 15",
    "PRJ-001","Legalization","@Phone","Next","Высокий","Средняя",
    "15","","","","","","",today,""
  ]]);
  sheet.getRange("A3:P3").setBackground("#fffde7");
  sheet.getRange("P3").setNote("Пример — удали эту строку");
}

// ─── WAITING FOR ──────────────────────────────────────────────────────────────

function _buildWaitingFor(sheetWaiting, sheetActions) {
  // Заголовок-пояснение
  sheetWaiting.getRange("A1").setValue("⏳ WAITING FOR — автоматический вид из NEXT ACTIONS");
  sheetWaiting.getRange("A1").setFontWeight("bold")
    .setFontColor("#A678E8").setFontSize(11);

  sheetWaiting.getRange("A2").setValue(
    "Этот лист показывает все действия со статусом 'Waiting' из листа NEXT ACTIONS."
  );
  sheetWaiting.getRange("A2").setFontColor("#666666").setFontSize(10);

  sheetWaiting.getRange("A3:P3").setValues([[
    "ID","Действие","Проект (ID)","Область (Area)",
    "Контекст","Статус","Приоритет","Энергия",
    "Время (мин)","Срок","Кому делегировано","Ждём от",
    "Ждём с","Заметки","Создано","Выполнено"
  ]]);

  var headerRange = sheetWaiting.getRange("A3:P3");
  headerRange.setBackground(HEADER_BG)
    .setFontColor(HEADER_FG)
    .setFontWeight("bold")
    .setFontSize(10);

  // FILTER формула
  sheetWaiting.getRange("A4").setFormula(
    "=IFERROR(FILTER('⚡ NEXT ACTIONS'!A2:P1000,'⚡ NEXT ACTIONS'!F2:F1000=\"Waiting\"),)"
  );

  // Условное форматирование: Waiting >7 дней — оранжевый
  var rule = SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=AND($M4<>"",$M4<TODAY()-7)')
    .setBackground("#fff3e0")
    .setRanges([sheetWaiting.getRange("A4:P1000")])
    .build();
  sheetWaiting.setConditionalFormatRules([rule]);

  sheetWaiting.setColumnWidth(1, 85);
  sheetWaiting.setColumnWidth(2, 320);
  sheetWaiting.setColumnWidth(3, 100);
  sheetWaiting.setColumnWidth(12, 140);
  sheetWaiting.setColumnWidth(13, 100);

  sheetWaiting.setFrozenRows(3);

  // Пояснение внизу
  sheetWaiting.getRange("A2").setNote(
    "Этот лист обновляется автоматически.\n" +
    "Чтобы добавить Waiting-задачу — иди в NEXT ACTIONS и поставь статус 'Waiting'.\n" +
    "Оранжевый фон = ожидаем больше 7 дней → нужен follow-up."
  );
}

// ─── SOMEDAY / MAYBE ──────────────────────────────────────────────────────────

function _buildSomeday(sheet) {
  var headers = [
    "ID","Идея / Проект","Описание","Область (Area)",
    "Пересмотреть","Статус","ID проекта (если активирован)","Добавлен"
  ];
  var widths = [85, 280, 350, 130, 110, 100, 160, 100];

  _writeHeaders(sheet, headers, widths);
  _freezeAndResize(sheet, 1, headers.length);

  _setDropdown(sheet, "D2:D1000", AREAS);
  _setDropdown(sheet, "F2:F1000", SOMEDAY_STATUSES);

  sheet.getRange("A2").setFormula('=IF(B2<>"","SOM-"&TEXT(ROW()-1,"000"),"")');

  var rules = [];
  // Активирован — зелёный
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$F2="Активирован"')
    .setFontColor("#2e7d32").setBackground("#e8f5e9")
    .setRanges([sheet.getRange("A2:H1000")]).build());
  // Пора пересмотреть — синий акцент
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=AND($F2="Ожидает",$E2<>"",$E2<=TODAY())')
    .setBackground(ACCENT_BG)
    .setRanges([sheet.getRange("A2:H1000")]).build());
  sheet.setConditionalFormatRules(rules);

  // Пример
  var today = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd");
  sheet.getRange("A3:H3").setValues([[
    "SOM-001","Запустить онлайн-курс по визам",
    "Серия обучающих видео + продажа через SendPulse",
    "Visas","2026-10-01","Ожидает","",today
  ]]);
  sheet.getRange("A3:H3").setBackground("#fffde7");
  sheet.getRange("H3").setNote("Пример — удали эту строку");
}

// ─── AREAS ────────────────────────────────────────────────────────────────────

function _buildAreas(sheet) {
  var headers = [
    "ID","Название","Описание","Google-аккаунт","Горизонт","Активна"
  ];
  var widths = [80, 160, 300, 170, 80, 80];

  _writeHeaders(sheet, headers, widths);
  _freezeAndResize(sheet, 1, headers.length);

  _setDropdown(sheet, "D2:D1000", GOOGLE_ACCOUNTS);
  _setDropdown(sheet, "E2:E1000", HORIZONS);
  _setDropdown(sheet, "F2:F1000", ["Да","Нет"]);

  // Заполнить Areas
  var areasData = [
    ["Business",       "Управление бизнесом в целом",           "Master (Личный)",        "H2","Да"],
    ["Finance",        "Личные и корпоративные финансы",        "Master (Личный)",        "H2","Да"],
    ["Investments",    "Инвестиции и портфель",                 "Master (Личный)",        "H2","Да"],
    ["Family",         "Семья и личные отношения",              "Master (Личный)",        "H2","Да"],
    ["Health",         "Физическое и ментальное здоровье",      "Master (Личный)",        "H2","Да"],
    ["Learning",       "Обучение и развитие",                   "Master (Личный)",        "H2","Да"],
    ["Coaching",       "Коучинговое направление",               "Google: Коучинг",        "H2","Да"],
    ["Real Estate",    "Недвижимость и объекты",                "Master (Личный)",        "H2","Да"],
    ["Visas",          "Визовое направление",                   "Google: Визы",           "H2","Да"],
    ["Legalization",   "Узаконение недвижимости",               "Google: Узаконение",     "H2","Да"],
    ["Marketing",      "Маркетинг и продвижение",               "Master (Личный)",        "H2","Да"],
    ["Sales",          "Продажи и CRM",                         "Master (Личный)",        "H2","Да"],
    ["Operations",     "Операционное управление",               "Google: Сотрудники",     "H2","Да"],
    ["IT",             "Технологии, инструменты, инфраструктура","Master (Личный)",       "H2","Да"],
    ["Automation",     "Автоматизация и AI-агенты",             "Master (Личный)",        "H2","Да"],
    ["Knowledge Base", "База знаний и документация",            "Master (Личный)",        "H2","Да"]
  ];

  for (var i = 0; i < areasData.length; i++) {
    var row = i + 2;
    sheet.getRange(row, 1).setValue("ARA-" + String(i + 1).padStart("3","0"));
    sheet.getRange(row, 2, 1, 5).setValues([areasData[i]]);
  }

  // Чередующийся фон
  for (var i = 0; i < areasData.length; i++) {
    if (i % 2 === 1) {
      sheet.getRange(i + 2, 1, 1, 6).setBackground(ROW_ALT_BG);
    }
  }

  // Неактивные — серые
  var rule = SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$F2="Нет"')
    .setFontColor(DONE_FG)
    .setRanges([sheet.getRange("A2:F1000")]).build();
  sheet.setConditionalFormatRules([rule]);
}

// ─── WEEKLY REVIEW ────────────────────────────────────────────────────────────

function _buildWeeklyReview(sheet) {
  var headers = [
    "Дата","Длит. (мин)","Inbox=0","Projects c NA",
    "Projects всего","% покрытия NA","Waiting просроч.",
    "Приоритет #1","Приоритет #2","Приоритет #3",
    "Оценка (1-5)","Заметки"
  ];
  var widths = [110,100,80,110,110,100,120,240,240,240,100,300];

  _writeHeaders(sheet, headers, widths);
  _freezeAndResize(sheet, 1, headers.length);

  _setDropdown(sheet, "C2:C1000", ["Да","Нет"]);

  // Авто-формулы
  // % покрытия NA = Projects с NA / Projects всего
  sheet.getRange("F2").setFormula('=IF(AND(D2<>"",E2<>"",E2>0),D2/E2,"")');
  sheet.getRange("F2").setNumberFormat("0%");

  // Условное форматирование
  var rules = [];
  // Inbox≠0 — красный
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$C2="Нет"')
    .setBackground(OVERDUE_BG)
    .setRanges([sheet.getRange("C2:C1000")]).build());
  // 100% NA покрытие — зелёный
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$F2=1')
    .setBackground("#e8f5e9").setFontColor("#2e7d32")
    .setRanges([sheet.getRange("F2:F1000")]).build());
  // Есть просроченные Waiting — оранжевый
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=AND($G2<>"",$G2>0)')
    .setBackground(WARNING_BG)
    .setRanges([sheet.getRange("G2:G1000")]).build());
  // Оценка 5 — зелёный
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$K2=5')
    .setBackground("#e8f5e9")
    .setRanges([sheet.getRange("K2:K1000")]).build());
  // Оценка <=2 — красный
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=AND($K2<>"",$K2<=2)')
    .setBackground(OVERDUE_BG)
    .setRanges([sheet.getRange("K2:K1000")]).build());

  sheet.setConditionalFormatRules(rules);

  // Пример строки
  var today = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd");
  sheet.getRange("A3:L3").setValues([[
    today, 65, "Да", 5, 6, "", 0,
    "Закрыть акт по объекту Абая 15",
    "Отправить КП клиенту Иванову",
    "Обновить шаблон договора",
    4, "Первый Review — всё настроено"
  ]]);
  sheet.getRange("F3").setFormula("=IF(AND(D3<>\"\",E3<>\"\",E3>0),D3/E3,\"\")");
  sheet.getRange("A3:L3").setBackground("#fffde7");
  sheet.getRange("L3").setNote("Пример — замени на свои данные");

  // Статистика — итоги (в нижней части или справа)
  sheet.getRange("N1").setValue("Статистика Reviews").setFontWeight("bold").setFontColor("#4BB543");
  sheet.getRange("N2").setValue("Всего Reviews:").setFontWeight("bold");
  sheet.getRange("O2").setFormula("=COUNTA(A2:A1000)");
  sheet.getRange("N3").setValue("Средняя оценка:").setFontWeight("bold");
  sheet.getRange("O3").setFormula("=IFERROR(AVERAGE(K2:K1000),\"\")");
  sheet.getRange("O3").setNumberFormat("0.0");
  sheet.getRange("N4").setValue("Inbox=0 (%)").setFontWeight("bold");
  sheet.getRange("O4").setFormula('=IFERROR(COUNTIF(C2:C1000,"Да")/COUNTA(C2:C1000),"")');
  sheet.getRange("O4").setNumberFormat("0%");
}

// ─── УТИЛИТЫ ──────────────────────────────────────────────────────────────────

// _getOrCreate удалён — логика перенесена в createGTDMasterSystem

function _writeHeaders(sheet, headers, widths) {
  var range = sheet.getRange(1, 1, 1, headers.length);
  range.setValues([headers]);
  range.setBackground(HEADER_BG);
  range.setFontColor(HEADER_FG);
  range.setFontWeight("bold");
  range.setFontSize(10);
  range.setVerticalAlignment("middle");
  sheet.setRowHeight(1, 32);

  if (widths) {
    for (var i = 0; i < widths.length; i++) {
      sheet.setColumnWidth(i + 1, widths[i]);
    }
  }
}

function _freezeAndResize(sheet, rows, cols) {
  sheet.setFrozenRows(rows);
  // Установить высоту строк данных
  sheet.setRowHeightsForced(2, 998, 24);
}

function _setDropdown(sheet, range, values) {
  var rule = SpreadsheetApp.newDataValidation()
    .requireValueInList(values, true)
    .setAllowInvalid(false)
    .build();
  sheet.getRange(range).setDataValidation(rule);
}

// Вспомогательный padStart для GAS (не поддерживает ES6 padStart)
String.prototype.padStart = String.prototype.padStart || function(len, fill) {
  var s = String(this);
  while (s.length < len) s = fill + s;
  return s;
};
