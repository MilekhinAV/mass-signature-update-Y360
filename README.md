# Mass Update Yandex 360 Mail Signatures
Скрипт для массового обновления **подписей в почте Яндекс 360** через [API 360](https://yandex.ru/support/yandex-360/business/admin/ru/security-service-applications).

## Возможности

- Массовая установка подписей по CSV (`userId,email,signature[,lang]`).
- Поддержка **полной замены** подписей или режима **merge** (обновление/добавление без удаления остальных).
- Проверка, что `email` из CSV принадлежит пользователю (основной ящик или алиас).
- Автоматическая подгрузка переменных окружения из `.env`.
- Опции:
  - `--dry-run` — тестовый прогон без изменений.
  - `--convert-newlines` — превращает `\n` в `<br>` внутри подписи.
  - `--rps` — ограничение запросов в секунду (по умолчанию 4).
  - `--strict-email` — если email не принадлежит пользователю, строка не применится (иначе подпись сохраняется без привязки к email).
  - `--position` — позиция подписи: `bottom` (по умолчанию) или `under`.

---

## Установка

1. Склонируйте репозиторий:

   ```bash
   git clone https://github.com/<your-org>/mass-y360-signatures.git
   cd mass-y360-signatures


2. Установите зависимости:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python3 -m pip install -r requirements.txt
   ```

   Файл `requirements.txt`:

   ```text
   requests
   python-dotenv
   ```

---

## Подготовка

### 1. Создать OAuth-токен администратора

* [Инструкция по созданию токена]([https://yandex.ru/dev/api360/doc/ru/concepts/intro](https://yandex.ru/support/yandex-360/business/admin/ru/security-service-applications)).

### 2. Настроить `.env`

Создайте файл `.env` в корне проекта:

```env
TOKEN=ya_oauth_...
ORG_ID=1234567
```

### 3. Подготовить CSV

Файл должен быть в UTF-8 и иметь заголовки: `userId,email,signature,lang`.

Пример с HTML-переносами:

```csv
userId,email,signature,lang
11300000,a.ivanov@company.ru,"С уважением,<br>Иванов Андрей<br>Должность1",ru
11300000,m.petrov@company.ru,"С уважением,<br>Петров Михаил<br>Должность2",ru
22333232,v.sidorov@company.ru,"С уважением,<br>Сидоров Антон<br>Должность3",ru
```

Пример с переносами `\n` (использовать с `--convert-newlines`):

```csv
userId,email,signature,lang
11300000,a.ivanov@company.ru,"С уважением,<br>Иванов Андрей<br>Должность1",ru
```

---

## Запуск

### Тестовый прогон (без применения)

```bash
python3 mass_set_signatures.py --csv employees_signs.csv --dry-run
```

### Применить подписи

```bash
python3 mass_set_signatures.py --csv employees_signs.csv
```

### Merge c существующими подписями

```bash
python3 mass_set_signatures.py --csv employees_signs.csv --merge
```

### Конвертировать `\n` в `<br>`

```bash
python3 mass_set_signatures.py --csv employees_signs.csv --convert-newlines
```

### Строгая проверка email

```bash
python3 mass_set_signatures.py --csv employees_signs.csv --strict-email
```

### Ограничить скорость запросов (2 RPS)

```bash
python3 mass_set_signatures.py --csv employees_signs.csv --rps 2
```

---

## Ограничения

* API 360 имеет rate limits — при больших загрузках используйте `--rps` и учитывайте возможные `429 Too Many Requests`.
* Метод **перезаписывает весь массив подписей** у пользователя. Чтобы сохранить существующие, используйте флаг `--merge`.
* HTML в `signature` должен быть валидным: используйте `<br>` для переносов строк.

---

## Лицензия

MIT


