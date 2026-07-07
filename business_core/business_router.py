"""
Business Router — определяет бизнес-контекст входящего сообщения.

Вызывается ПОСЛЕ GTD-классификации через process_item().
Не заменяет GTD — добавляет бизнес-измерение к уже готовому GTD-результату.

Уровни роутинга (в порядке вызова):
  1. Ключевые слова (без AI, мгновенно)
  2. Поиск клиента в тексте (по People Registry)
  3. Определение города (по списку)
  4. AI-роутинг (только если confidence < 0.7, требует ANTHROPIC_API_KEY)
"""

from __future__ import annotations

import os
import re
import logging
from typing import Optional

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Результат роутинга (пустой шаблон)
# ─────────────────────────────────────────────────────────────

def _empty_routing() -> dict:
    return {
        "business_id":        "",
        "business_name":      "",
        "service_id":         "",
        "service_name":       "",
        "city":               "",
        "client_id":          "",
        "client_name":        "",
        "process":            "",
        "roadmap_id":         "",
        "roadmap_stage_id":   "",
        "roadmap_stage_name": "",
        "confidence":         0.0,
        "needs_confirmation": True,
        "routing_method":     "none",
        "matched_keywords":   [],
    }


# ─────────────────────────────────────────────────────────────
# Ключевые слова по бизнесам
# ─────────────────────────────────────────────────────────────

# Формат: { slug: (список ключевых слов, вес) }
# Чем длиннее/специфичнее слово — тем выше вес
BUSINESS_KEYWORDS: dict[str, list[tuple[str, float]]] = {
    "legalization": [
        ("узаконение", 0.9),   ("узаконить", 0.9),   ("узаконивание", 0.9),
        ("легализация", 0.9),  ("легализовать", 0.9),
        ("акт ввода", 0.95),   ("акт приёмки", 0.9),
        ("техпаспорт", 0.85),  ("технический паспорт", 0.9),
        ("техобследование", 0.85), ("топосъемка", 0.85),
        ("бти", 0.85),         ("цон", 0.7),
        ("апз", 0.9),          ("архитектурно-планировочное", 0.95),
        ("самострой", 0.9),    ("самовольное", 0.85),
        ("гараж", 0.6),        ("частный дом", 0.7),
        ("узаконение гаража", 0.95), ("узаконение дома", 0.95),
        ("регистрация объект", 0.8), ("ввод в эксплуатацию", 0.9),
        ("егрн", 0.8),
    ],
    "visas": [
        ("виза", 0.9),         ("визы", 0.9),
        ("загранпаспорт", 0.85), ("загран", 0.7),
        ("нотариус", 0.7),     ("нотариальный перевод", 0.9),
        ("апостиль", 0.9),     ("консульство", 0.85),
        ("посольство", 0.85),  ("шенген", 0.9),
        ("рвп", 0.85),         ("вид на жительство", 0.9),
        ("гражданство", 0.7),  ("документы для визы", 0.95),
        ("туристическая виза", 0.95), ("рабочая виза", 0.95),
    ],
    "coaching": [
        ("коучинг", 0.95),     ("коуч", 0.85),
        ("ментор", 0.85),      ("менторинг", 0.9),
        ("стратегическая сессия", 0.95), ("стратсессия", 0.95),
        ("воркшоп", 0.85),     ("тренинг", 0.7),
        ("личная эффективность", 0.85), ("развитие", 0.4),
        ("карьера", 0.5),      ("жизненная стратегия", 0.9),
    ],
    "investments": [
        ("инвестиции", 0.9),   ("инвестировать", 0.9),
        ("портфель", 0.75),    ("доходность", 0.7),
        ("рентабельность", 0.7), ("инвестиционный", 0.85),
        ("пассивный доход", 0.85), ("рентный доход", 0.9),
        ("купить объект", 0.7), ("арендный бизнес", 0.9),
    ],
    "automation": [
        ("автоматизация", 0.9), ("автоматизировать", 0.9),
        ("telegram бот", 0.95), ("телеграм бот", 0.95),
        ("чат-бот", 0.9),      ("чатбот", 0.9),
        ("интеграция api", 0.9), ("n8n", 0.95),
        ("make.com", 0.95),    ("zapier", 0.9),
        ("crm интеграция", 0.85), ("автоворонка", 0.85),
        ("webhook", 0.85),     ("sendpulse", 0.8),
        ("binotel", 0.8),      ("waba", 0.8),
    ],
}

# Города (в порядке убывания приоритета)
KNOWN_CITIES = [
    "нур-султан", "астана", "алматы", "шымкент",
    "актобе", "тараз", "павлодар", "усть-каменогорск",
    "семей", "атырау", "костанай", "кызылорда",
    "петропавловск", "актау", "темиртау", "туркестан",
    "онлайн", "удалённо",
]

# GTD-области → slug бизнеса
AREA_TO_SLUG: dict[str, str] = {
    "Legalization": "legalization",
    "Visas":        "visas",
    "Coaching":     "coaching",
    "Investments":  "investments",
    "Automation":   "automation",
}

# Бизнес-GTD-области (роутинг только для них)
BUSINESS_AREAS = set(AREA_TO_SLUG.keys()) | {
    "Business", "Operations", "Sales", "Marketing", "IT",
}


# ─────────────────────────────────────────────────────────────
# Уровень 1: ключевые слова
# ─────────────────────────────────────────────────────────────

def _route_by_keywords(
    text: str,
    businesses: list[dict],
) -> tuple[str, str, float, list[str]]:
    """
    Матч по ключевым словам.

    Returns:
        (biz_id, slug, confidence, matched_keywords)
    """
    text_lower = text.lower()

    # Сначала попробуем по области GTD если она уже определена
    scores: dict[str, float] = {}
    matched: dict[str, list[str]] = {}

    for slug, keywords in BUSINESS_KEYWORDS.items():
        total = 0.0
        found = []
        for kw, weight in keywords:
            if kw in text_lower:
                total += weight
                found.append(kw)
        if total > 0:
            scores[slug] = min(total, 1.0)
            matched[slug] = found

    if not scores:
        return ("", "", 0.0, [])

    best_slug = max(scores, key=lambda s: scores[s])
    best_score = scores[best_slug]

    # Найти business_id по slug
    biz_id = ""
    for biz in businesses:
        biz_slug = biz.get("slug", "")
        if biz_slug == best_slug:
            biz_id = biz.get("id", "")
            break

    return (biz_id, best_slug, best_score, matched.get(best_slug, []))


# ─────────────────────────────────────────────────────────────
# Уровень 2: поиск клиента
# ─────────────────────────────────────────────────────────────

def _find_client_in_text(
    text: str,
    people: list[dict],
) -> tuple[str, str, float]:
    """
    Найти имя клиента в тексте по People Registry.

    Returns:
        (person_id, person_name, confidence)
    """
    if not people:
        return ("", "", 0.0)

    text_lower = text.lower()

    for person in people:
        full_name = person.get("full_name", "") or person.get("ФИО", "")
        short_name = person.get("short_name", "") or person.get("Имя", "")
        person_id = person.get("id", "") or person.get("ID", "")

        # Проверяем фамилию (первое слово полного имени)
        parts = full_name.split()
        if parts:
            surname = parts[0].lower()
            if len(surname) >= 3 and surname in text_lower:
                return (person_id, full_name, 0.85)

        # Проверяем короткое имя
        if short_name and len(short_name) >= 3:
            if short_name.lower() in text_lower:
                return (person_id, full_name or short_name, 0.75)

        # Проверяем полное имя целиком
        if full_name and len(full_name) >= 5:
            if full_name.lower() in text_lower:
                return (person_id, full_name, 0.95)

    # Клиент не найден в базе — ищем фамилии по паттерну (обязательны типичные окончания)
    name_pattern = re.compile(
        r'\b([А-ЯЁ][а-яё]{3,}(?:ов|ова|ев|ева|ин|ина|ский|ская|ного|ной|нов|нова|иев|иева|ян|яна))\b'
    )
    matches = name_pattern.findall(text)
    if matches:
        return ("", matches[0], 0.5)

    return ("", "", 0.0)


# ─────────────────────────────────────────────────────────────
# Уровень 3: определение города
# ─────────────────────────────────────────────────────────────

def _find_city_in_text(text: str) -> str:
    """
    Определить город из текста.

    Returns:
        Название города с заглавной буквы или ""
    """
    text_lower = text.lower()
    for city in KNOWN_CITIES:
        # Убираем последний символ для склонений: "Астаны"→корень "астан",
        # "Алматы" → "алмат", "Шымкент" (заканчивается на согласную) → без изменений.
        # Это обеспечивает матч для всех падежных форм.
        if len(city) > 4:
            root = city[:-1]
        else:
            root = city
        if re.search(r'\b' + re.escape(root), text_lower):
            return city.capitalize()
    return ""


# ─────────────────────────────────────────────────────────────
# Уровень 4: AI-роутинг (опциональный)
# ─────────────────────────────────────────────────────────────

def _route_by_ai(
    text: str,
    businesses: list[dict],
    services: list[dict],
    gtd_area: str = "",
) -> tuple[str, str, float]:
    """
    AI-роутинг через Claude для неоднозначных случаев.
    Вызывается только если confidence < 0.7.

    Returns:
        (biz_id, service_id, confidence)
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        log.debug("AI-роутинг пропущен: ANTHROPIC_API_KEY не задан")
        return ("", "", 0.0)

    try:
        import anthropic

        biz_list = "\n".join(
            f"  {b.get('id','?')} | {b.get('name','?')} | slug={b.get('slug','?')}"
            for b in businesses[:10]
        )
        svc_list = "\n".join(
            f"  {s.get('id','?')} | {s.get('name','?')} | biz={s.get('business_id','?')}"
            for s in services[:20]
        )

        prompt = (
            f"Определи к какому бизнесу и услуге относится этот текст:\n\n"
            f"Текст: «{text}»\n"
            f"GTD-область: {gtd_area}\n\n"
            f"Доступные бизнесы:\n{biz_list}\n\n"
            f"Доступные услуги:\n{svc_list}\n\n"
            f"Отвечай строго в формате (одна строка):\n"
            f"BIZ_ID: <id или пусто> | SVC_ID: <id или пусто> | CONFIDENCE: <0.0-1.0>"
        )

        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=128,
            messages=[{"role": "user", "content": prompt}],
        )
        response = msg.content[0].text.strip()

        biz_match = re.search(r"BIZ_ID:\s*(BIZ-\d+)", response)
        svc_match = re.search(r"SVC_ID:\s*(SVC-\d+)", response)
        conf_match = re.search(r"CONFIDENCE:\s*([\d.]+)", response)

        biz_id = biz_match.group(1) if biz_match else ""
        svc_id = svc_match.group(1) if svc_match else ""
        confidence = float(conf_match.group(1)) if conf_match else 0.5

        log.debug(f"AI routing: biz={biz_id} svc={svc_id} conf={confidence}")
        return (biz_id, svc_id, confidence)

    except Exception as e:
        log.warning(f"AI-роутинг ошибка: {e}")
        return ("", "", 0.0)


# ─────────────────────────────────────────────────────────────
# Определение услуги по бизнесу и тексту
# ─────────────────────────────────────────────────────────────

def _find_service(
    text: str,
    biz_id: str,
    services: list[dict],
) -> tuple[str, str]:
    """
    Найти услугу по тексту внутри найденного бизнеса.

    Returns:
        (service_id, service_name)
    """
    if not biz_id or not services:
        return ("", "")

    biz_services = [
        s for s in services
        if s.get("business_id", "") == biz_id or s.get("Бизнес ID", "") == biz_id
    ]

    text_lower = text.lower()
    for svc in biz_services:
        name = svc.get("name", "") or svc.get("Название", "")
        svc_id = svc.get("id", "") or svc.get("ID", "")
        if name and name.lower() in text_lower:
            return (svc_id, name)

        # Проверяем ключевые слова из названия услуги
        name_words = [w for w in name.lower().split() if len(w) > 4]
        matches = sum(1 for w in name_words if w in text_lower)
        if matches >= 2:
            return (svc_id, name)

    return ("", "")


# ─────────────────────────────────────────────────────────────
# Определение этапа
# ─────────────────────────────────────────────────────────────

# Ключевые слова этапов → название этапа
STAGE_KEYWORDS: dict[str, list[str]] = {
    "Диагностика кейса":    ["диагностика кейса", "анализ кейса", "изучить объект", "первичная консультация"],
    "Сбор документов":      ["собрать документы", "документы от клиента", "запросить документы"],
    "АПЗ":                  ["апз", "архитектурно-планировочное", "задание"],
    "Проект":               ["проект", "проектирование", "чертёж"],
    "Техобследование":      ["техобследование", "техническое обследование", "обследование объекта"],
    "Топосъемка":           ["топосъемка", "топографическая", "геодезия"],
    "Техпаспорт":           ["техпаспорт", "технический паспорт", "бти"],
    "Акт ввода":            ["акт ввода", "ввод в эксплуатацию", "акт приёмки"],
    "Регистрация":          ["регистрация", "егрн", "постановка на учёт"],
    "Архив":                ["архив", "закрыть", "завершить кейс"],
}


def _find_roadmap_stage(text: str) -> tuple[str, str]:
    """
    Определить этап дорожной карты по тексту.

    Returns:
        (stage_id_placeholder, stage_name)
        stage_id — пустой (реальный ID будет из Roadmap Manager)
    """
    text_lower = text.lower()
    for stage_name, keywords in STAGE_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                return ("", stage_name)
    return ("", "")


# ─────────────────────────────────────────────────────────────
# Главная функция
# ─────────────────────────────────────────────────────────────

def route_business_context(
    original_text: str,
    gtd_result: dict,
    businesses: list[dict],
    services: list[dict] | None = None,
    people: list[dict] | None = None,
    use_ai: bool = True,
) -> dict:
    """
    Определить бизнес-контекст входящего сообщения.

    Вызывается после process_item() из GTD.
    Не создаёт GTD-записи — только добавляет контекст.

    Args:
        original_text:  исходный текст пользователя
        gtd_result:     результат process_item() (словарь с ключами результат/действие/область/...)
        businesses:     список бизнесов (list[BusinessArea.to_dict()] или list[dict])
        services:       список услуг (может быть пустым на старте)
        people:         список людей для поиска клиента
        use_ai:         разрешить ли AI-роутинг при низком confidence

    Returns:
        dict с ключами: business_id, service_id, city, client_id,
                        roadmap_stage_name, confidence, needs_confirmation, ...
    """
    if services is None:
        services = []
    if people is None:
        people = []

    routing = _empty_routing()
    text = original_text.strip()

    if not text or not businesses:
        return routing

    gtd_area = gtd_result.get("область", "")
    gtd_action = gtd_result.get("действие", "")

    # Комбинируем текст + GTD-действие для более точного матча
    combined_text = f"{text} {gtd_action}".strip()

    # ── Шаг 1: Попытка по GTD-области ──────────────────────────
    area_slug = AREA_TO_SLUG.get(gtd_area, "")
    if area_slug:
        for biz in businesses:
            if biz.get("slug", "") == area_slug:
                routing["business_id"]   = biz.get("id", "")
                routing["business_name"] = biz.get("name", "")
                routing["confidence"]    = 0.75
                routing["routing_method"] = "gtd_area"
                break

    # ── Шаг 2: Ключевые слова ───────────────────────────────────
    kw_biz_id, kw_slug, kw_conf, kw_matched = _route_by_keywords(combined_text, businesses)

    if kw_conf > routing["confidence"]:
        for biz in businesses:
            if biz.get("id", "") == kw_biz_id:
                routing["business_id"]   = kw_biz_id
                routing["business_name"] = biz.get("name", "")
                break
        routing["confidence"]       = kw_conf
        routing["routing_method"]   = "keyword_match"
        routing["matched_keywords"] = kw_matched

    # ── Шаг 3: Определение города ───────────────────────────────
    city = _find_city_in_text(combined_text)
    if city:
        routing["city"] = city

    # ── Шаг 4: Поиск клиента ────────────────────────────────────
    if people:
        client_id, client_name, client_conf = _find_client_in_text(combined_text, people)
        if client_name:
            routing["client_id"]   = client_id
            routing["client_name"] = client_name
            # Наличие известного клиента повышает confidence
            if client_id:
                routing["confidence"] = min(routing["confidence"] + 0.1, 1.0)

    # ── Шаг 5: Определение услуги ───────────────────────────────
    if routing["business_id"] and services:
        svc_id, svc_name = _find_service(combined_text, routing["business_id"], services)
        if svc_id:
            routing["service_id"]   = svc_id
            routing["service_name"] = svc_name
            routing["confidence"]   = min(routing["confidence"] + 0.05, 1.0)

    # ── Шаг 6: Определение этапа ────────────────────────────────
    _, stage_name = _find_roadmap_stage(combined_text)
    if stage_name:
        routing["roadmap_stage_name"] = stage_name

    # ── Шаг 7: AI-роутинг при низком confidence ─────────────────
    if use_ai and routing["confidence"] < 0.7 and routing["business_id"] == "":
        ai_biz_id, ai_svc_id, ai_conf = _route_by_ai(
            text, businesses, services, gtd_area
        )
        if ai_conf > routing["confidence"]:
            routing["confidence"]     = ai_conf
            routing["routing_method"] = "ai"
            if ai_biz_id:
                routing["business_id"] = ai_biz_id
                for biz in businesses:
                    if biz.get("id", "") == ai_biz_id:
                        routing["business_name"] = biz.get("name", "")
                        break
            if ai_svc_id:
                routing["service_id"] = ai_svc_id

    # ── Шаг 8: Финальное решение ─────────────────────────────────
    routing["needs_confirmation"] = (
        routing["confidence"] < 0.9
        or routing["business_id"] == ""
        or (routing["client_name"] and routing["client_id"] == "")
    )

    # Определяем бизнес-процесс по типу GTD-результата
    if routing["business_id"]:
        gtd_type = gtd_result.get("результат", "")
        if gtd_type == "Waiting":
            routing["process"] = "Ожидание"
        elif routing["roadmap_stage_name"]:
            routing["process"] = "Производство"
        elif gtd_type in ("Action", "Project"):
            routing["process"] = "Операционка"

    log.debug(
        f"route_business_context: biz={routing['business_id']} "
        f"city={routing['city']} client={routing['client_name']} "
        f"conf={routing['confidence']:.2f} method={routing['routing_method']}"
    )

    return routing


# ─────────────────────────────────────────────────────────────
# Проверка: нужно ли вызывать Business Router
# ─────────────────────────────────────────────────────────────

def should_route(gtd_result: dict) -> bool:
    """
    Проверить, нужно ли вызывать Business Router для данного GTD-результата.

    Business Router вызывается только для:
    - Action / Project / Waiting
    - Область входит в BUSINESS_AREAS

    Returns:
        True если нужно роутить
    """
    gtd_type = gtd_result.get("результат", "")
    gtd_area = gtd_result.get("область", "")

    if gtd_type not in ("Action", "Project", "Waiting"):
        return False

    if gtd_area in BUSINESS_AREAS:
        return True

    # Если область не задана — роутить (AI сам разберётся)
    if not gtd_area:
        return True

    return False


# ─────────────────────────────────────────────────────────────
# Форматирование для Telegram
# ─────────────────────────────────────────────────────────────

def format_routing_confirmation(routing: dict) -> str:
    """
    Сформировать текст для подтверждения роутинга пользователем.
    Показывается когда needs_confirmation=True или confidence < 0.9.
    """
    conf_pct = int(routing["confidence"] * 100)
    conf_icon = "🟢" if conf_pct >= 90 else "🟡" if conf_pct >= 70 else "🔴"

    lines = [
        f"🏢 *Бизнес-контекст определён {conf_icon} {conf_pct}%*",
        "",
    ]

    if routing["business_name"]:
        lines.append(f"📌 Бизнес: {routing['business_name']}")
    if routing["service_name"]:
        lines.append(f"🛠 Услуга: {routing['service_name']}")
    if routing["city"]:
        lines.append(f"📍 Город: {routing['city']}")
    if routing["client_name"]:
        client_str = routing["client_name"]
        if not routing["client_id"]:
            client_str += " _(не в базе)_"
        lines.append(f"👤 Клиент: {client_str}")
    if routing["roadmap_stage_name"]:
        lines.append(f"📋 Этап: {routing['roadmap_stage_name']}")

    if routing["matched_keywords"]:
        kw_str = ", ".join(routing["matched_keywords"][:3])
        lines.append(f"🔍 Ключевые слова: _{kw_str}_")

    if routing["needs_confirmation"]:
        lines.extend([
            "",
            "Верно определил контекст?",
            "✅ Да  /  ❌ Нет, исправить",
        ])

    return "\n".join(lines)


def format_routing_note(routing: dict) -> str:
    """
    Краткая заметка для записи в GTD Next Action (поле Notes).
    """
    parts = []
    if routing["business_id"]:
        parts.append(f"biz:{routing['business_id']}")
    if routing["client_id"]:
        parts.append(f"client:{routing['client_id']}")
    elif routing["client_name"]:
        parts.append(f"client_name:{routing['client_name']}")
    if routing["city"]:
        parts.append(f"city:{routing['city']}")
    if routing["roadmap_stage_name"]:
        parts.append(f"stage:{routing['roadmap_stage_name']}")
    return " | ".join(parts)
