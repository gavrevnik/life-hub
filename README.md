# Life Hub

Локальный launcher для сервисов из общего каталога `life-stack`. Он показывает карточки приложений, проверяет их локальные health endpoints, запускает заранее описанные macOS-приложения и безопасно останавливает их по PID-файлам.

## Запуск

На macOS дважды нажмите [Life Hub.app](Life%20Hub.app). Launcher поднимет внутренний сервер на `http://127.0.0.1:8790` и откроет [http://life-hub.localhost](http://life-hub.localhost).

При обновлении кода launcher сверяет версию `/api/health` и безопасно перезапускает только собственный устаревший процесс Life Hub. Если порт занят другим приложением, оно не завершается.

### Автозапуск и закладка Chrome

Чтобы адрес Life Hub всегда открывался из закладки, один раз установите пользовательский macOS LaunchAgent:

```bash
python3 scripts/install_autostart.py
```

Он сразу запускает Life Hub и затем запускает его автоматически при каждом входе в macOS. Сервер остаётся привязан к `127.0.0.1`. Для удаления автозапуска и остановки хаба:

```bash
python3 scripts/install_autostart.py --uninstall
```

После установки откройте [http://life-hub.localhost](http://life-hub.localhost), добавьте страницу в папку «Панель закладок» (`⌘D`) и включите панель сочетанием `⇧⌘B`. Страница содержит собственный favicon, поэтому название закладки можно удалить и оставить только иконку.

Ручной запуск:

```bash
python3 app/server.py
```

## Локальные адреса

[`Caddyfile`](Caddyfile) проксирует понятные адреса `.localhost` на внутренние loopback-порты. Caddy слушает только `127.0.0.1`; записи в `/etc/hosts` не нужны.

```bash
brew install caddy
ln -s "$PWD/Caddyfile" "$(brew --prefix)/etc/Caddyfile"
sudo brew services start caddy
```

Системный режим нужен только для стандартного HTTP-порта 80; macOS один раз запросит пароль администратора. После этого Caddy запускается автоматически вместе с системой.

Доступные адреса:

- `http://life-hub.localhost`
- `http://activity-checker.localhost`
- `http://jobs-checker.localhost`
- `http://voice-translator.localhost`
- `http://content-checker.localhost`

Вкладка хаба и вкладки сервисов отправляют локальный heartbeat. Если heartbeat полностью исчезает (например, браузер закрыт), через 5 минут Life Hub останавливает сервисы с `stopWhenBrowserIdle: true`, но сам остаётся доступен для следующего открытия из закладки. Очистка выполняется один раз за период простоя и снова включается после появления новой вкладки. Таймер можно переопределить параметром `--idle-timeout` или переменной `LIFE_HUB_IDLE_TIMEOUT_SECONDS`. На карточке каждого запущенного сервиса также доступна ручная кнопка «Остановить».

## Registry

`registry.json` содержит отображаемое имя, публичный `.localhost` URL, прямой `directUrl`, health endpoint, GitHub URL, относительные пути к `.app` и PID-файлу каждого сервиса, а также политику `stopWhenBrowserIdle`. Пути разрешаются только внутри родительского каталога `life-stack`; произвольные команды из HTTP-запросов не выполняются. Перед остановкой PID дополнительно сверяется с каталогом репозитория, поэтому посторонний процесс не завершается. Если PID-файл устарел, Hub восстанавливает PID по локальному порту из `directUrl`, но только после той же проверки каталога процесса; одно совпадение порта не даёт права на остановку.

Значение `stopWhenBrowserIdle: false` оставляет конкретный сервис работать в фоне после выключения хаба. Ручная кнопка «Остановить» остаётся доступна независимо от этой настройки.

Текущий registry:

- Activity Checker
- Jobs checker
- Voice Translator
- Content Checker

## Проверка

```bash
python3 -m unittest discover -s tests
python3 -m compileall app
```
