# Загрузка системы без логина

## Выбор scope
Проверь systemctl show <реальный-unit-gateway> и systemctl --user show <реальный-unit-gateway>: User, Group, FragmentPath, UnitFileState, Wants, After. Не выводи Environment целиком: там могут быть секреты. Уточни UID владельца, абсолютный путь поддерживаемого Node и CLI, доступность HOME при загрузке (зашифрованный home может требовать входа).

Если Gateway — системный unit, установи отдельный системный voice unit с User/Group того же непривилегированного владельца и WantedBy=multi-user.target. Gateway и слушатель не должны работать от root ради доступа к аудио.
Если Gateway — пользовательский unit, можно оставить voice unit в пользовательском manager, но явно включить lingering. Это запуск при boot, не только при login. Объясни пользователю выбранную архитектуру.

В обоих случаях пользовательский PipeWire/WirePlumber должен стартовать при boot и иметь доступ к нужному устройству без GUI. Проверь loginctl show-user <USER> -p Linger. loginctl enable-linger <USER> запускает manager при загрузке и сохраняет после logout: https://www.freedesktop.org/software/systemd/man/256/loginctl.html .
Включи существующие pipewire.service/сокеты и wireplumber.service средствами установленного дистрибутива; проверь их unit dependencies и состояние. Не запускай второй конкурирующий аудиосервер.

## Системный unit-шаблон
Подставь локальные значения вместо всех угловых скобок; это шаблон, не готовая команда. Оба unit-имени в зависимостях относятся к системному scope. Для user service не переносить эти зависимости дословно.

[Unit]
Description=OpenClaw local smart speaker
Wants=network-online.target user@<UID>.service <GATEWAY_SYSTEM_UNIT>
After=network-online.target user@<UID>.service <GATEWAY_SYSTEM_UNIT>

[Service]
Type=simple
User=<USER>
Group=<GROUP>
WorkingDirectory=<APP_DIR>
Environment=HOME=<HOME_DIR>
Environment=XDG_RUNTIME_DIR=/run/user/<UID>
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/<UID>/bus
Environment=PATH=<SUPPORTED_NODE_BIN_DIR>:<OPENCLAW_BIN_DIR>:/usr/local/bin:/usr/bin:/bin
Environment=HF_HUB_OFFLINE=1
EnvironmentFile=<ABSOLUTE_VOICE_ENV_FILE>
ExecStart=<VENV_DIR>/bin/python -u <APP_DIR>/speaker.py
Restart=on-failure
RestartSec=5
KillMode=control-group
TimeoutStopSec=10
UMask=0077

[Install]
WantedBy=multi-user.target

EnvironmentFile содержит VOICE_ROOT, VOICE_MIC, VOICE_SINK, VOICE_AGENT, VOICE_WAKE, VOICE_SESSION, VOICE_OPENCLAW, VOICE_GAIN, VOICE_FOLLOWUP_SECONDS. Это не shell: не используй $HOME и командные подстановки. В нём не нужны токены. Ограничь права доступа, а пути и значения экранируй по правилам systemd.

Для user unit используй After/Wants=pipewire.service wireplumber.service и реальный user Gateway unit при его наличии, убери User/Group, используй WantedBy=default.target; XDG_RUNTIME_DIR предоставляется manager. Убедись, что lingering включён. Системный voice unit не может упорядочить user pipewire.service директивой After=pipewire.service: readiness проверяется фактическим pw-dump и ожиданием устройств.

## Аудиоправа до login
Изучи владельца/группу и ACL /dev/snd, группы сервисного пользователя и политику дистрибутива. Активная desktop-сессия может временно выдавать ACL; это не гарантия headless boot. Если штатный способ — членство в audio, предоставь его только владельцу аудиосервера, объяснив постоянный доступ к аудиоустройствам, и обнови процессы, чтобы новые группы реально применились. Альтернатива — узкое distro-supported udev-правило для выбранного устройства. Не используй chmod 666 и не запускай PipeWire от root. Перезапуск user manager затрагивает все его сервисы: выполняй в согласованное окно.

Сверь с локальными man systemd.service, systemd.exec, loginctl и документацией дистрибутива. Не объявляй одну схему udev универсальной. Если headless-аудио недоступно, зафиксируй блокер, а не подменяй требование GUI-autologin.

## Ввод в эксплуатацию
1. Сохрани исходный unit/env и enabled/active-состояние; проверь новый unit через systemd-analyze verify.
2. Проверь CLI агент и mpv из будущего runtime-контекста, не только интерактивного shell.
3. Перед включением нового system unit останови и отключи предыдущий user voice unit: одновременно должен слушать один процесс. Сначала убедись, что откат готов.
4. Выполни daemon-reload и enable --now в правильном scope. Проверь статус и журнал, реальный вход и выход. enabled не доказывает доступность устройств.
5. В согласованное время перезагрузи хост, не выполняя GUI login. Проверь время старта user manager/аудио/voice/Gateway относительно boot. Контроль через административное подключение не должен сам запускать сервисы; при SSH под тем же владельцем опирайся на журнал старта ДО SSH либо используй другой административный аккаунт.
6. Попроси пользователя сказать wake+вопрос и подтвердить ответ. Если проверить boot без логина сейчас нельзя, явно пометь его как непроверенный; не перезагружай активную машину скрытно ради отчёта.

Системный сервис: systemctl status/start/stop/restart <VOICE_UNIT>, journalctl -u <VOICE_UNIT>.
Пользовательский: systemctl --user status/start/stop/restart <VOICE_UNIT>, journalctl --user -u <VOICE_UNIT>.
Откат: останови/отключи новый unit, восстанови сохранённые файлы, daemon-reload и прежние enabled/active состояния; восстанови исходную TTS-конфигурацию, если менялась. Откатывай lingering/группы лишь если их добавил именно этот запуск и они не нужны Gateway/другим сервисам.
