import subprocess
import sys
import os
import random
import string
import pwd
import grp
import time
import datetime
import threading
from flask import Flask, request, jsonify
import argparse
from tinydb import TinyDB, Query
import logging

app = Flask(__name__)

LOWER_DIR = "/mnt/games"          # Локальная нижняя директория
EXPORTS_ROOT = "/srv/exports"     # Директории для OverlayFS
SMB_CONF = "/etc/samba/smb.conf" # Файл конфигурации Samba
SMB_USER = "root"                 # Новый пользователь Samba
DB_FILE = "alina_db.json"         # Файл базы данных TinyDB
LOG_FILE = "alina.log"            # Файл логов

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

# Инициализация базы данных TinyDB
db = TinyDB(DB_FILE)
folders_table = db.table('folders')

def run_cmd(cmd, check=True):
    logging.debug(f"run_cmd: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.stdout:
            logging.debug(f"STDOUT: {result.stdout.strip()}")
        if result.stderr:
            logging.debug(f"STDERR: {result.stderr.strip()}")
        return result
    except subprocess.CalledProcessError as e:
        logging.error(f"Команда {' '.join(cmd)} завершилась с ошибкой: {e.stderr.strip()}")
        if check:
            raise
        return e

def ensure_packages():
    run_cmd(["apt-get", "update", "-y"], check=True)
    run_cmd(["apt-get", "install", "-y", "samba", "python3-pip", "rsync"], check=True)
    run_cmd(["pip3", "install", "flask", "tinydb"], check=True)

def backup_smb_conf():
    timestamp = int(time.time())
    backup_path = f"{SMB_CONF}.backup_{timestamp}"
    run_cmd(["cp", SMB_CONF, backup_path], check=False)
    logging.info(f"Создана резервная копия {SMB_CONF} в {backup_path}")

def setup_lowerdir():
    logging.info(f"Создаём нижнюю директорию: {LOWER_DIR}")
    os.makedirs(LOWER_DIR, exist_ok=True)

def init_smb():
    logging.info("Инициализация Samba-сервера")
    run_cmd(["systemctl", "enable", "smbd"], check=False)
    run_cmd(["systemctl", "start", "smbd"], check=False)

def reload_smb_config():
    logging.info("Перезагружаем конфигурацию Samba без перезапуска службы")
    run_cmd(["smbcontrol", "smbd", "reload-config"], check=False)

def add_smb_share(folder):
    share_name = folder
    share_path = os.path.join(EXPORTS_ROOT, folder, "merged")

    logging.info(f"Добавляем общую папку в Samba: {share_name}")

    if not os.path.exists(SMB_CONF):
        logging.error(f"Файл конфигурации Samba не найден: {SMB_CONF}")
        sys.exit(1)

    with open(SMB_CONF, "r") as f:
        lines = f.readlines()

    share_header = f"[{share_name}]\n"
    if share_header in lines:
        logging.info(f"Запись для {share_name} уже существует в smb.conf")
        return

    # Резервное копирование конфигурации перед изменениями
    backup_smb_conf()

    with open(SMB_CONF, "a") as f:
        f.write(f"\n[{share_name}]\n")
        f.write(f"  path = {share_path}\n")
        f.write("  read only = no\n")
        f.write("  writeable = yes\n")
        f.write(f"  valid users = {SMB_USER}\n")  # Разрешаем доступ только пользователю 'SMB_USER'
        f.write("  # guest ok = no\n")             # Отключаем гостевой доступ
        f.write("  force create mode = 0775\n")    # Настраиваем более строгие права
        f.write("  force directory mode = 0775\n")
        f.write(f"  force user = {SMB_USER}\n")    # Заменяем 'nobody' на 'SMB_USER'
        f.write(f"  force group = {SMB_USER}\n")   # Устанавливаем группу пользователя

    # Перезагрузка конфигурации Samba
    reload_smb_config()
    logging.info(f"SMB-шара {share_name} успешно добавлена и конфигурация перезагружена")

def remove_smb_share(folder):
    share_name = folder
    logging.info(f"Удаляем SMB-шару: {share_name}")

    if not os.path.exists(SMB_CONF):
        logging.error(f"Файл конфигурации Samba не найден: {SMB_CONF}")
        return

    with open(SMB_CONF, "r") as f:
        lines = f.readlines()

    share_header = f"[{share_name}]\n"
    if share_header not in lines:
        logging.info(f"Запись для {share_name} не найдена в smb.conf")
        return

    # Найти индекс начала и конца секции SMB-шары
    start_idx = lines.index(share_header)
    end_idx = start_idx + 1
    while end_idx < len(lines) and not lines[end_idx].startswith('['):
        end_idx += 1

    # Удалить секцию
    del lines[start_idx:end_idx]

    # Резервное копирование конфигурации перед изменениями
    backup_smb_conf()

    # Записать обратно файл
    with open(SMB_CONF, "w") as f:
        f.writelines(lines)

    # Перезагрузка конфигурации Samba
    reload_smb_config()
    logging.info(f"SMB-шара {share_name} успешно удалена из {SMB_CONF} и конфигурация перезагружена")

def setup_env():
    ensure_packages()
    setup_lowerdir()
    init_smb()

def create_overlay_mount(folder):
    lower_dir = LOWER_DIR
    upper_dir = os.path.join(EXPORTS_ROOT, folder, "upper")
    work_dir = os.path.join(EXPORTS_ROOT, folder, "work")
    merge_dir = os.path.join(EXPORTS_ROOT, folder, "merged")

    os.makedirs(upper_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(merge_dir, exist_ok=True)

    # Установка владельца и группы на SMB_USER:SMB_USER
    try:
        user_info = pwd.getpwnam(SMB_USER)
        group_info = grp.getgrnam(SMB_USER)
    except KeyError:
        logging.error(f"Пользователь или группа '{SMB_USER}' не найдены.")
        sys.exit(1)

    for directory in [upper_dir, work_dir, merge_dir]:
        os.chown(directory, user_info.pw_uid, group_info.gr_gid)
        os.chmod(directory, 0o775)  # Устанавливаем более строгие права

    logging.info(f"Создаём OverlayFS для {folder}")
    run_cmd([
        "mount", "-t", "overlay",
        "overlay",
        "-o", f"lowerdir={lower_dir},upperdir={upper_dir},workdir={work_dir}",
        merge_dir
    ], check=True)

    add_smb_share(folder)
    logging.info(f"SMB-шара добавлена для {merge_dir}")

@app.route("/create_folder", methods=["POST"])
def http_create_folder():
    data = request.get_json(force=True, silent=True) or {}
    folder = data.get("folder")
    if not folder:
        folder = "rand_" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))

    try:
        create_overlay_mount(folder)
        expiration_time = datetime.datetime.utcnow() + datetime.timedelta(hours=12)
        folders_table.insert({
            'folder': folder,
            'expiration': expiration_time.timestamp()
        })
        return jsonify({"status": "ok", "folder": folder}), 200
    except Exception as e:
        logging.error(f"Ошибка при создании папки: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500

def alina_thread():
    while True:
        try:
            current_time = datetime.datetime.utcnow().timestamp()
            Folder = Query()
            expired_folders = folders_table.search(Folder.expiration <= current_time)

            for entry in expired_folders:
                folder = entry['folder']
                logging.info(f"Удаляем OverlayFS для {folder}")
                merged_path = os.path.join(EXPORTS_ROOT, folder, "merged")
                work_path = os.path.join(EXPORTS_ROOT, folder, "work")
                upper_path = os.path.join(EXPORTS_ROOT, folder, "upper")

                run_cmd(["umount", merged_path], check=False)
                for path in [merged_path, work_path, upper_path]:
                    if os.path.exists(path):
                        run_cmd(["rm", "-rf", path], check=False)

                # Удаляем SMB-шару
                remove_smb_share(folder)

                # Удаляем запись из базы данных
                folders_table.remove(Folder.folder == folder)
                logging.info(f"Папка {folder} успешно удалена")
        except Exception as e:
            logging.error(f"Ошибка в alina_thread: {e}")

        time.sleep(60)

def main():
    parser = argparse.ArgumentParser(description="Настраивает OverlayFS + SMB окружение и запускает Flask API.")
    parser.add_argument("--port", type=int, default=5000, help="Порт для Flask-API")
    args = parser.parse_args()

    setup_env()

    logging.info(f"Flask API слушает на порту {args.port}")
    alina_thr = threading.Thread(target=alina_thread)
    alina_thr.daemon = True
    alina_thr.start()
    app.run(host="0.0.0.0", port=args.port)

if __name__ == "__main__":
    if os.geteuid() != 0:
        logging.error("Запустите скрипт от root (sudo)!")
        sys.exit(1)
    main()
