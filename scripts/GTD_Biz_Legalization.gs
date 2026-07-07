/**
 * GTD BIZ · УЗАКОНЕНИЕ — Google Apps Script
 * ───────────────────────────────────────────
 * Запускай в: Extensions → Apps Script → Run → createGTDBizLegalization
 *
 * Что создаёт:
 *   1. 👥 КЛИЕНТЫ
 *   2. 🏠 ОБЪЕКТЫ
 *   3. 📋 ЭТАПЫ РАБОТ
 *   4. 📄 ДОКУМЕНТЫ
 *   + Валидация, форматирование, примеры строк, связанные формулы
 */

// ─── КОНСТАНТЫ ────────────────────────────────────────────────────────────────

var CLIENT_STATUSES  = ["Активный","Завершён","Приостановлен","Архив"];
var SERVICE_TYPES    = [
  "Узаконение ИЖС","Узаконение МЖД","Перепланировка","Раздел/Объединение",
  "Смена целевого назначения","Ввод в эксплуатацию","Тех. надзор","Другое"
];
var OBJECT_TYPES     = ["ИЖС","МЖД","Коммерческий","Промышленный","Земельный участок","Другое"];
var CITIES           = ["Алматы","Астана","Шымкент","Другой"];
var WORK_STAGES      = [
  "Первичный осмотр","Сбор документов","Техпаспорт",
  "Проект","Экспертиза","Акимат","БТИ регистрация",
  "Ввод в эксплуатацию","Акт подписан","Архив"
];
var STAGE_STATUSES   = ["Ожидает","В работе","На проверке","Выполнен","Заблокирован","Отменён"];
var DOC_TYPES        = [
  "Договор","Акт","Техпаспорт","Проект","Заключение экспертизы",
  "Постановление акимата","Свидетельство о регистрации","Доверенность",
  "Удостоверение личности","Правоустанавливающий документ","КП","Другое"
];
var DOC_STATUSES     = ["Ожидается","В работе","Получен","Подписан","Сдан","Архив"];
var SOURCES          = ["Рекомендация","Instagram","WhatsApp","Сайт","Другое"];
var PAYMENT_STATUSES = ["Не оплачен","Частично","Полностью","Возврат"];
var RESPONSIBLE_LIST = ["Вы","Сотрудник 1","Сотрудник 2","Подрядчик","—"];

var HEADER_BG  = "#1a1a2e";
var HEADER_FG  = "#ffffff";
var ROW_ALT_BG = "#f8f9fa";
var DONE_FG    = "#9e9e9e";
var OVERDUE_BG = "#fce4e4";
var WARNING_BG = "#fff8e1";
var SUCCESS_BG = "#e8f5e9";

// ─── ГЛАВНАЯ ФУНКЦИЯ ──────────────────────────────────────────────────────────

function createGTDBizLegalization() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  ss.setName("GTD Biz · Узаконение");

  var keeper = ss.getSheets()[0];

  var sheetClients  = _getOrCreate(ss, "👥 КЛИЕНТЫ",       "#4B91F7", keeper);
  var sheetObjects  = _getOrCreate(ss, "🏠 ОБЪЕКТЫ",       "#4BB543", keeper);
  var sheetStages   = _getOrCreate(ss, "📋 ЭТАПЫ РАБОТ",   "#E8A838", keeper);
  var sheetDocs     = _getOrCreate(ss, "📄 ДОКУМЕНТЫ",     "#7E8EAA", keeper);

  try { ss.deleteSheet(keeper); } catch(e) {}

  var order = [sheetClients, sheetObjects, sheetStages, sheetDocs];
  for (var i = 0; i < order.length; i++) {
    ss.setActiveSheet(order[i]);
    ss.moveActiveSheet(i + 1);
  }

  _buildClients(sheetClients);
  _buildObjects(sheetObjects);
  _buildStages(sheetStages);
  _buildDocuments(sheetDocs);

  ss.setActiveSheet(sheetClients);

  SpreadsheetApp.getUi().alert(
    "✅ GTD Biz · Узаконение создан!\n\n" +
    "4 листа готовы:\n" +
    "👥 КЛИЕНТЫ\n🏠 ОБЪЕКТЫ\n📋 ЭТАПЫ РАБОТ\n📄 ДОКУМЕНТЫ\n\n" +
    "Следующие шаги:\n" +
    "1. Добавь существующих клиентов в КЛИЕНТЫ\n" +
    "2. Для каждого клиента создай объект в ОБЪЕКТЫ\n" +
    "3. Добавь этапы работ в ЭТАПЫ РАБОТ\n" +
    "4. Для каждого объекта создай проект в GTD Master System"
  );
}

// ─── КЛИЕНТЫ ──────────────────────────────────────────────────────────────────

function _buildClients(sheet) {
  var headers = [
    "ID","ФИО / Компания","Телефон","WhatsApp","Email",
    "Статус клиента","Тип услуги","Откуда пришёл",
    "Дата обращения","ID Проекта (Master)","Папка Drive",
    "Сумма договора (тг)","Оплачено (тг)","Остаток (тг)",
    "Статус оплаты","Город","Заметки"
  ];
  var widths = [80,220,130,130,180,110,160,120,120,130,200,140,120,110,110,100,250];

  _writeHeaders(sheet, headers, widths);
  _freezeAndResize(sheet, 1, headers.length);

  _setDropdown(sheet, "F2:F1000", CLIENT_STATUSES);
  _setDropdown(sheet, "G2:G1000", SERVICE_TYPES);
  _setDropdown(sheet, "H2:H1000", SOURCES);
  _setDropdown(sheet, "O2:O1000", PAYMENT_STATUSES);
  _setDropdown(sheet, "P2:P1000", CITIES);

  // Авто-ID
  sheet.getRange("A2").setFormula('=IF(B2<>"","CLN-"&TEXT(ROW()-1,"000"),"")');

  // Авто-остаток = Сумма - Оплачено
  sheet.getRange("N2").setFormula("=IF(AND(L2<>\"\",M2<>\"\"),L2-M2,\"\")");
  sheet.getRange("L2:N2").setNumberFormat("#,##0 ₸");

  var rules = [];
  // Завершён — серый
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$F2="Завершён"')
    .setFontColor(DONE_FG)
    .setRanges([sheet.getRange("A2:Q1000")]).build());
  // Остаток > 0 + активный — желтый
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=AND($F2="Активный",$N2>0)')
    .setBackground(WARNING_BG)
    .setRanges([sheet.getRange("N2:N1000")]).build());
  // Полностью оплачен — зелёный
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$O2="Полностью"')
    .setBackground(SUCCESS_BG).setFontColor("#2e7d32")
    .setRanges([sheet.getRange("O2:O1000")]).build());

  sheet.setConditionalFormatRules(rules);

  // Пример
  var today = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd");
  sheet.getRange("A3:Q3").setValues([[
    "CLN-001","Иванов Алексей Александрович",
    "+7 777 000 00 01","+7 777 000 00 01","ivanov@mail.ru",
    "Активный","Узаконение ИЖС","Рекомендация",
    today,"PRJ-001","",
    250000, 150000, "", "Частично", "Алматы",
    "Объект: ул. Абая 15"
  ]]);
  sheet.getRange("N3").setFormula("=IF(AND(L3<>\"\",M3<>\"\"),L3-M3,\"\")");
  sheet.getRange("L3:N3").setNumberFormat("#,##0 ₸");
  sheet.getRange("A3:Q3").setBackground("#fffde7");
  sheet.getRange("Q3").setNote("Пример — замени на своих клиентов");

  // Итоги внизу — сводка по статусам оплаты
  sheet.getRange("S1").setValue("Сводка").setFontWeight("bold");
  sheet.getRange("S2").setValue("Всего клиентов:");
  sheet.getRange("T2").setFormula('=COUNTA(B2:B1000)');
  sheet.getRange("S3").setValue("Активных:");
  sheet.getRange("T3").setFormula('=COUNTIF(F2:F1000,"Активный")');
  sheet.getRange("S4").setValue("Общая сумма договоров:");
  sheet.getRange("T4").setFormula("=SUM(L2:L1000)");
  sheet.getRange("T4").setNumberFormat("#,##0 ₸");
  sheet.getRange("S5").setValue("Оплачено итого:");
  sheet.getRange("T5").setFormula("=SUM(M2:M1000)");
  sheet.getRange("T5").setNumberFormat("#,##0 ₸");
  sheet.getRange("S6").setValue("Остаток дебиторки:");
  sheet.getRange("T6").setFormula("=SUM(N2:N1000)");
  sheet.getRange("T6").setNumberFormat("#,##0 ₸");
  sheet.getRange("S1:T6").setBackground("#f3f4f6");
  sheet.setColumnWidth(19, 180);
  sheet.setColumnWidth(20, 130);
}

// ─── ОБЪЕКТЫ ──────────────────────────────────────────────────────────────────

function _buildObjects(sheet) {
  var headers = [
    "ID","Адрес","Тип объекта","Клиент (ID)","Клиент (ФИО)",
    "Город","Текущий этап","Статус","Площадь (м²)",
    "Год постройки","Кадастровый номер","Папка Drive","Заметки"
  ];
  var widths = [80,280,140,100,200,100,160,100,90,110,160,200,250];

  _writeHeaders(sheet, headers, widths);
  _freezeAndResize(sheet, 1, headers.length);

  _setDropdown(sheet, "C2:C1000", OBJECT_TYPES);
  _setDropdown(sheet, "F2:F1000", CITIES);
  _setDropdown(sheet, "G2:G1000", WORK_STAGES);
  _setDropdown(sheet, "H2:H1000", ["В работе","Завершён","Приостановлен","Архив"]);

  sheet.getRange("A2").setFormula('=IF(B2<>"","OBJ-"&TEXT(ROW()-1,"000"),"")');

  // Авто-подтягивание ФИО клиента по ID
  sheet.getRange("E2").setFormula(
    "=IFERROR(VLOOKUP(D2,'👥 КЛИЕНТЫ'!A:B,2,FALSE),\"\")"
  );

  var rules = [];
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$H2="Завершён"')
    .setFontColor(DONE_FG)
    .setRanges([sheet.getRange("A2:M1000")]).build());
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$H2="В работе"')
    .setBackground("#e3f2fd")
    .setRanges([sheet.getRange("A2:A1000")]).build());
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$G2="Акт подписан"')
    .setBackground(SUCCESS_BG).setFontColor("#2e7d32")
    .setRanges([sheet.getRange("G2:G1000")]).build());
  sheet.setConditionalFormatRules(rules);

  // Пример
  sheet.getRange("A3:M3").setValues([[
    "OBJ-001","ул. Абая 15, Алматы","ИЖС","CLN-001","",
    "Алматы","Техпаспорт","В работе",
    120, 2015,"", "","2-этажный дом"
  ]]);
  sheet.getRange("E3").setFormula(
    "=IFERROR(VLOOKUP(D3,'👥 КЛИЕНТЫ'!A:B,2,FALSE),\"\")"
  );
  sheet.getRange("A3:M3").setBackground("#fffde7");
  sheet.getRange("M3").setNote("Пример — замени на свои объекты");
}

// ─── ЭТАПЫ РАБОТ ──────────────────────────────────────────────────────────────

function _buildStages(sheet) {
  var headers = [
    "Объект (ID)","Адрес объекта","Этап","Статус",
    "Ответственный","Срок","Выполнен","Заметки"
  ];
  var widths = [100, 250, 180, 120, 130, 100, 100, 280];

  _writeHeaders(sheet, headers, widths);
  _freezeAndResize(sheet, 1, headers.length);

  _setDropdown(sheet, "C2:C1000", WORK_STAGES);
  _setDropdown(sheet, "D2:D1000", STAGE_STATUSES);
  _setDropdown(sheet, "E2:E1000", RESPONSIBLE_LIST);

  // Авто-адрес объекта по ID
  sheet.getRange("B2").setFormula(
    "=IFERROR(VLOOKUP(A2,'🏠 ОБЪЕКТЫ'!A:B,2,FALSE),\"\")"
  );

  var rules = [];
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$D2="Выполнен"')
    .setFontColor(DONE_FG).setStrikethrough(true)
    .setRanges([sheet.getRange("A2:H1000")]).build());
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=AND($D2<>"Выполнен",$F2<TODAY(),$F2<>"")')
    .setBackground(OVERDUE_BG)
    .setRanges([sheet.getRange("A2:H1000")]).build());
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$D2="В работе"')
    .setBackground("#e3f2fd")
    .setRanges([sheet.getRange("A2:H1000")]).build());
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$D2="Заблокирован"')
    .setBackground(OVERDUE_BG).setFontColor("#c62828")
    .setRanges([sheet.getRange("A2:H1000")]).build());
  sheet.setConditionalFormatRules(rules);

  // Стандартный набор этапов для объекта OBJ-001
  var stages = [
    ["OBJ-001","","Первичный осмотр",    "Выполнен", "Вы",        "", Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd"), ""],
    ["OBJ-001","","Сбор документов",     "В работе", "Сотрудник 1","2026-07-20","",""],
    ["OBJ-001","","Техпаспорт",          "Ожидает",  "Сотрудник 1","2026-08-01","",""],
    ["OBJ-001","","Проект",              "Ожидает",  "Подрядчик", "2026-08-15","",""],
    ["OBJ-001","","Экспертиза",          "Ожидает",  "Вы",        "2026-09-01","",""],
    ["OBJ-001","","Акимат",              "Ожидает",  "Вы",        "2026-09-15","",""],
    ["OBJ-001","","БТИ регистрация",     "Ожидает",  "Вы",        "2026-10-01","",""],
    ["OBJ-001","","Ввод в эксплуатацию", "Ожидает",  "Вы",        "2026-10-15","",""],
    ["OBJ-001","","Акт подписан",        "Ожидает",  "Вы",        "2026-11-01","",""]
  ];

  for (var i = 0; i < stages.length; i++) {
    var row = i + 2;
    sheet.getRange(row, 1, 1, 8).setValues([stages[i]]);
    sheet.getRange(row, 2).setFormula(
      "=IFERROR(VLOOKUP(A" + row + ",'🏠 ОБЪЕКТЫ'!A:B,2,FALSE),\"\")"
    );
    if (i % 2 === 1) sheet.getRange(row, 1, 1, 8).setBackground(ROW_ALT_BG);
  }
  sheet.getRange("H10").setNote("Это пример этапов для OBJ-001 — замени на реальные данные");

  // Счётчик в шапке
  sheet.getRange("J1").setValue("Статистика").setFontWeight("bold").setFontColor("#E8A838");
  sheet.getRange("J2").setValue("Всего этапов:");
  sheet.getRange("K2").setFormula('=COUNTA(A2:A1000)');
  sheet.getRange("J3").setValue("Выполнено:");
  sheet.getRange("K3").setFormula('=COUNTIF(D2:D1000,"Выполнен")');
  sheet.getRange("J4").setValue("В работе:");
  sheet.getRange("K4").setFormula('=COUNTIF(D2:D1000,"В работе")');
  sheet.getRange("J5").setValue("Заблокировано:");
  sheet.getRange("K5").setFormula('=COUNTIF(D2:D1000,"Заблокирован")');
  sheet.getRange("J6").setValue("Просрочено:");
  sheet.getRange("K6").setFormula('=COUNTIFS(D2:D1000,"<>Выполнен",F2:F1000,"<"&TODAY(),F2:F1000,"<>")');
  sheet.getRange("J1:K6").setBackground("#f3f4f6");
  sheet.setColumnWidth(10, 130);
  sheet.setColumnWidth(11, 80);
}

// ─── ДОКУМЕНТЫ ────────────────────────────────────────────────────────────────

function _buildDocuments(sheet) {
  var headers = [
    "ID","Объект (ID)","Адрес объекта","Тип документа",
    "Название","Статус","Дата","Ссылка Drive","Заметки"
  ];
  var widths = [80, 100, 250, 180, 250, 110, 100, 250, 200];

  _writeHeaders(sheet, headers, widths);
  _freezeAndResize(sheet, 1, headers.length);

  _setDropdown(sheet, "D2:D1000", DOC_TYPES);
  _setDropdown(sheet, "F2:F1000", DOC_STATUSES);

  sheet.getRange("A2").setFormula('=IF(B2<>"","DOC-"&TEXT(ROW()-1,"000"),"")');

  // Авто-адрес по ID объекта
  sheet.getRange("C2").setFormula(
    "=IFERROR(VLOOKUP(B2,'🏠 ОБЪЕКТЫ'!A:B,2,FALSE),\"\")"
  );

  var rules = [];
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$F2="Получен"')
    .setBackground(SUCCESS_BG).setFontColor("#2e7d32")
    .setRanges([sheet.getRange("F2:F1000")]).build());
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$F2="Подписан"')
    .setBackground("#e8f5e9").setFontColor("#1b5e20")
    .setRanges([sheet.getRange("F2:F1000")]).build());
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$F2="Ожидается"')
    .setBackground(WARNING_BG)
    .setRanges([sheet.getRange("F2:F1000")]).build());
  sheet.setConditionalFormatRules(rules);

  // Примеры документов
  var today = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd");
  var examples = [
    ["DOC-001","OBJ-001","","Договор","Договор на услуги с Ивановым А.А.","Подписан",today,"",""],
    ["DOC-002","OBJ-001","","Правоустанавливающий документ","Свидетельство о праве собственности","Получен",today,"",""],
    ["DOC-003","OBJ-001","","Техпаспорт","Технический паспорт объекта","Ожидается","","","Заказан в БТИ"],
  ];

  for (var i = 0; i < examples.length; i++) {
    var row = i + 2;
    sheet.getRange(row, 1, 1, 9).setValues([examples[i]]);
    sheet.getRange(row, 3).setFormula(
      "=IFERROR(VLOOKUP(B" + row + ",'🏠 ОБЪЕКТЫ'!A:B,2,FALSE),\"\")"
    );
    if (i % 2 === 1) sheet.getRange(row, 1, 1, 9).setBackground(ROW_ALT_BG);
  }
  sheet.getRange("A2:I4").setBackground("#fffde7");
  sheet.getRange("I4").setNote("Примеры — замени на реальные документы");

  // Сводка
  sheet.getRange("K1").setValue("Документы").setFontWeight("bold").setFontColor("#7E8EAA");
  sheet.getRange("K2").setValue("Всего:");
  sheet.getRange("L2").setFormula('=COUNTA(B2:B1000)');
  sheet.getRange("K3").setValue("Получено:");
  sheet.getRange("L3").setFormula('=COUNTIF(F2:F1000,"Получен")');
  sheet.getRange("K4").setValue("Ожидается:");
  sheet.getRange("L4").setFormula('=COUNTIF(F2:F1000,"Ожидается")');
  sheet.getRange("K5").setValue("Подписано:");
  sheet.getRange("L5").setFormula('=COUNTIF(F2:F1000,"Подписан")');
  sheet.getRange("K1:L5").setBackground("#f3f4f6");
  sheet.setColumnWidth(11, 110);
  sheet.setColumnWidth(12, 80);
}

// ─── УТИЛИТЫ ──────────────────────────────────────────────────────────────────

function _getOrCreate(ss, name, color, keeper) {
  var existing = ss.getSheetByName(name);
  if (existing) {
    existing.clearContents();
    existing.clearFormats();
    existing.setConditionalFormatRules([]);
    existing.setTabColor(color);
    return existing;
  }
  var sheet = ss.insertSheet(name);
  sheet.setTabColor(color);
  return sheet;
}

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
  sheet.setRowHeightsForced(2, 998, 24);
}

function _setDropdown(sheet, range, values) {
  var rule = SpreadsheetApp.newDataValidation()
    .requireValueInList(values, true)
    .setAllowInvalid(false)
    .build();
  sheet.getRange(range).setDataValidation(rule);
}

String.prototype.padStart = String.prototype.padStart || function(len, fill) {
  var s = String(this);
  while (s.length < len) s = fill + s;
  return s;
};
