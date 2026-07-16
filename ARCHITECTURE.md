# BUSINESS CORE ARCHITECTURE

## Общая архитектура

GTD Core

│

├── Inbox

├── Projects

├── Calendar

├── Reference

└── Next Actions

Business Core

│

├── Business

│

├── Client

│

├── Object

│

├── Service

│

├── Roadmap

│

├── Stages

│

├── Documents

│

├── Contractors

│

└── Reports

---

## Иерархия

Business

↓

Client

↓

Object

↓

Service

↓

Roadmap

↓

Stage

---

## Источник данных

Google Sheets

↓

Business Core

↓

Telegram Bot

↓

Пользователь

---

## Документы

Google Drive

Business

↓

Client

↓

Object

↓

Service

↓

Documents

---

## Каналы

Binotel

↓

SendPulse

↓

Business Core

↓

Telegram

---

## Главный принцип

Business Core является единственным источником истины.

Никакая другая система не хранит бизнес-логику.

SendPulse отвечает только за продажи.

Binotel отвечает только за телефонию.

Google Drive отвечает только за документы.

Telegram является интерфейсом сотрудников.

Google Sheets является текущей базой данных.