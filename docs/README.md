## 🛠️ Обновление сервиса (ежедневная рутина)

```bash
cd
cd ~/icambio/icambio_shipbot
git pull
sudo systemctl restart icambio-shipbot
sudo journalctl -u icambio-shipbot -f
```

