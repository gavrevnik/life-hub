# Life Hub

Локальный launcher для сервисов из общего каталога `life-stack`. Он показывает карточки приложений, проверяет их локальные health endpoints и запускает только заранее описанные macOS-приложения.

## Запуск

На macOS дважды нажмите [Life Hub.app](Life%20Hub.app). Launcher поднимет сервер на `http://127.0.0.1:8790` и откроет браузер.

Ручной запуск:

```bash
python3 app/server.py
```

## Registry

`registry.json` содержит отображаемое имя, описание, локальный URL, health endpoint, GitHub URL и относительный путь к `.app` каждого сервиса. Пути разрешаются только внутри родительского каталога `life-stack`; произвольные команды из HTTP-запросов не выполняются.

Текущий registry:

- Activity Checker
- Jobs Checker
- Voice Translator
- Content Checker

## Проверка

```bash
python3 -m unittest discover -s tests
python3 -m compileall app
```
