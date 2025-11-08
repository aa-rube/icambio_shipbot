# 🚀 `icambio-shipbot`

---

## 🛠️ Обновление сервиса (ежедневная рутина)

```bash
sudo systemctl daemon-reload
cd
cd ~/icambio/icambio_shipbot
git pull
sudo systemctl restart icambio-shipbot
sudo journalctl -u icambio-shipbot -f
```

---

## 📦 Установка и настройка `icambio-shipbot`

### 1️⃣ Создание виртуального окружения

```bash
sudo mkdir -p /opt/venvs/shipbot
sudo chown icambio:icambio /opt/venvs/shipbot
python3 -m venv /opt/venvs/shipbot
source /opt/venvs/shipbot/bin/activate
```

---

### 2️⃣ Установка зависимостей

```bash
pip install -U pip setuptools wheel
pip install -r ~/icambio/icambio_shipbot/requirements.txt
```

*(если были ошибки прав — можно удалить окружение и повторить под пользователем `icambio`, **без sudo**)*

---

### 3️⃣ Проверка локального запуска

```bash
cd ~/icambio/icambio_shipbot
/opt/venvs/shipbot/bin/python bot.py
```

Если бот запустился — значит всё ок.

---

### 4️⃣ Создание systemd сервиса

Создаём файл `/etc/systemd/system/icambio-shipbot.service`:

```bash
sudo nano /etc/systemd/system/icambio-shipbot.service
```

Вставляем:

```ini
[Unit]
Description=iCambio ShipBot
After=network.target

[Service]
Type=simple
User=icambio
WorkingDirectory=/home/icambio/icambio/icambio_shipbot
EnvironmentFile=/home/icambio/icambio/icambio_shipbot/.env
ExecStart=/opt/venvs/shipbot/bin/python /home/icambio/icambio/icambio_shipbot/bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

---

### 5️⃣ Проверка прав

```bash
sudo chown -R icambio:icambio /home/icambio/icambio/icambio_shipbot
sudo chown -R icambio:icambio /opt/venvs/shipbot
sudo chmod +x /opt/venvs/shipbot/bin/python
sudo chmod 640 /home/icambio/icambio/icambio_shipbot/.env
```

---

### 6️⃣ Запуск и автозагрузка

```bash
sudo systemctl daemon-reload
sudo systemctl enable icambio-shipbot
sudo systemctl restart icambio-shipbot
sudo journalctl -u icambio-shipbot -f
```

---

## ⚙️ Диагностика ошибок

Если сервис не запускается:

```bash
sudo journalctl -u icambio-shipbot -n 50 --no-pager
```

Проверь:

```bash
ls -l /opt/venvs/shipbot/bin/python
ls -l /home/icambio/icambio/icambio_shipbot/.env
sudo -u icambio /opt/venvs/shipbot/bin/python /home/icambio/icambio/icambio_shipbot/bot.py
```

---

Хочешь, я сделаю короткий bash-скрипт (`deploy_shipbot.sh`), который автоматизирует обновление и перезапуск этой схемы одной командой (`bash deploy_shipbot.sh`)?


