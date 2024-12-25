import subprocess
import sys
import os
import json
import random
import string
import pwd
import grp
from flask import Flask, request, jsonify
import argparse

app = Flask(__name__)

LOWER_DIR = "/mnt/games"         # Локальная нижняя директория
EXPORTS_ROOT = "/srv/exports"    # Директории для OverlayFS
SMB_CONF = "/etc/samba/smb.conf" # Файл конфигурации Samba
SMB_USER = "root"                # Новый пользователь Samba

def run_cmd(cmd, check=True):
    print(f"[DEBUG] run_cmd: {' '.join(cmd)}")
    result = subprocess.run(cmd, check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.stdout:
        print("[DEBUG STDOUT]", result.stdout.strip())
    if result.stderr:
        print("[DEBUG STDERR]", result.stderr.strip())
    return result

def ensure_packages():
    run_cmd(["apt-get", "update", "-y"], check=True)
    run_cmd(["apt-get", "install", "-y", "samba", "python3-pip", "rsync"], check=True)
    run_cmd(["pip3", "install", "flask"], check=True)

def setup_lowerdir():
    print("[INFO] Создаём нижнюю директорию:", LOWER_DIR)
    os.makedirs(LOWER_DIR, exist_ok=True)

def init_smb():
    print("[INFO] Инициализация Samba-сервера")
    run_cmd(["systemctl", "enable", "smbd"], check=False)
    run_cmd(["systemctl", "restart", "smbd"], check=False)

def add_smb_share(folder):
    share_name = folder
    share_path = os.path.join(EXPORTS_ROOT, folder, "merged")

    print(f"[INFO] Добавляем общую папку в Samba: {share_name}")

    with open(SMB_CONF, "r") as f:
        lines = f.readlines()

    if f"[{share_name}]\n" in lines:
        print(f"[INFO] Запись для {share_name} уже существует в smb.conf")
        return

    with open(SMB_CONF, "a") as f:
        f.write(f"\n[{share_name}]\n")
        f.write(f"  path = {share_path}\n")
        f.write("  read only = no\n")
        f.write("  writeable = yes\n")
        f.write(f"  valid users = {SMB_USER}\n")  # Разрешаем доступ только пользователю 'user'
        f.write("  # guest ok = no\n")  # Отключаем гостевой доступ
        f.write("  force create mode = 0775\n")  # Настраиваем более строгие права
        f.write("  force directory mode = 0775\n")
        f.write(f"  force user = {SMB_USER}\n")  # Заменяем 'nobody' на 'user'
        f.write(f"  force group = {SMB_USER}\n")  # Устанавливаем группу пользователя

    run_cmd(["systemctl", "restart", "smbd"], check=False)

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

    # Установка владельца и группы на user:user
    try:
        user_info = pwd.getpwnam(SMB_USER)
        group_info = grp.getgrnam(SMB_USER)
    except KeyError:
        print(f"[ERROR] Пользователь или группа '{SMB_USER}' не найдены.")
        sys.exit(1)

    for directory in [upper_dir, work_dir, merge_dir]:
        os.chown(directory, user_info.pw_uid, group_info.gr_gid)
        os.chmod(directory, 0o775)  # Устанавливаем более строгие права

    print(f"[INFO] Создаём OverlayFS для {folder}")
    run_cmd([
        "mount", "-t", "overlay",
        "overlay",
        "-o", f"lowerdir={lower_dir},upperdir={upper_dir},workdir={work_dir}",
        merge_dir
    ], check=True)

    add_smb_share(folder)
    print(f"[INFO] SMB общая папка добавлена для {merge_dir}")

@app.route("/create_folder", methods=["POST"])
def http_create_folder():
    data = request.get_json(force=True, silent=True) or {}
    folder = data.get("folder")
    if not folder:
        folder = "rand_" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))

    try:
        create_overlay_mount(folder)
        return jsonify({"status": "ok", "folder": folder}), 200
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

def main():
    parser = argparse.ArgumentParser(description="Настраивает OverlayFS + SMB окружение и запускает Flask API.")
    parser.add_argument("--port", type=int, default=5000, help="Порт для Flask-API")
    args = parser.parse_args()

    setup_env()

    print(f"[INFO] Flask API слушает на порту {args.port}")
    app.run(host="0.0.0.0", port=args.port)

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("[ERROR] Запустите скрипт от root (sudo)!")
        sys.exit(1)
    main()