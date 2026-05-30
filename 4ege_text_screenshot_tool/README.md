# Скриншоты раскрытого блока «Текст» с 4ЕГЭ

Этот пакет предназначен для автоматического сохранения PNG-скриншотов исходных текстов к вариантам 1–50 со страницы:

https://4ege.ru/russkiy/76504-sochinenija-k-sborniku-ra-doschinskogo-50-variantov-ege-2026.html?ysclid=mpst3c2my6359558868

## Запуск в Windows PowerShell

```powershell
py -m pip install playwright
py -m playwright install chromium
py capture_4ege_text_screens.py --url "https://4ege.ru/russkiy/76504-sochinenija-k-sborniku-ra-doschinskogo-50-variantov-ege-2026.html?ysclid=mpst3c2my6359558868"
```

## Что получится

В папке `out` появятся:

- `screens/` — PNG-скриншоты по вариантам;
- `texts/` — извлечённые исходные тексты в TXT;
- `links_1_50.json` — соответствие номера варианта и ссылки;
- `report.json` — отчёт по успешным и проблемным страницам;
- `4ege_doschinsky_text_screens.zip` — архив со всеми результатами.

## Проверка

Если сайт изменит вёрстку или временно отдаст рекламу/капчу, часть вариантов может попасть в `errors` в `report.json`.
В таком случае запусти с видимым браузером:

```powershell
py capture_4ege_text_screens.py --headful --slow 200
```
