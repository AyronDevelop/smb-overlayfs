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
import socket

app = Flask(__name__)

# Параметры
LOWER_DIR = "/mnt/games"          # Локальная нижняя директория
EXPORTS_ROOT = "/srv/exports"     # Директории для OverlayFS
EXPORTS_LV = "/dev/vg0/exports"   # Логический том, где расположены данные (настройте под вашу систему)
SMB_CONF = "/etc/samba/smb.conf"  # Файл конфигурации Samba
SMB_USER = "root"                 # Пользователь для Samba
DB_FILE = "alina_db.json"         # Файл базы данных TinyDB
LOG_FILE = "alina.log"            # Файл логов
ISCSI_BASE_IQN = "iqn.2025-03.local.alina"  # Базовый IQN для iSCSI

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

def run_cmd(cmd, check=True, **kwargs):
    # Если shell=True и команда передана списком, приводим её к строке
    if kwargs.get("shell", False) and isinstance(cmd, list):
        cmd = " ".join(cmd)
    logging.debug(f"run_cmd: {cmd}")
    try:
        result = subprocess.run(cmd, check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kwargs)
        if result.stdout:
            logging.debug(f"STDOUT: {result.stdout.strip()}")
        if result.stderr:
            logging.debug(f"STDERR: {result.stderr.strip()}")
        return result
    except subprocess.CalledProcessError as e:
        logging.error(f"Команда {cmd} завершилась с ошибкой: {e.stderr.strip()}")
        if check:
            raise
        return e

def ensure_packages():
    run_cmd(["apt-get", "update", "-y"], check=True)
    # Используем tgt вместо targetcli для Debian/Ubuntu
    run_cmd(["apt-get", "install", "-y", "samba", "python3-pip", "rsync", "tgt", "lvm2"], check=True)
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

def get_server_ip():
    """Получаем IP-адрес сервера для настройки iSCSI"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_address = s.getsockname()[0]
        s.close()
        return ip_address
    except Exception as e:
        logging.warning(f"Не удалось автоматически определить IP: {e}")
        return "0.0.0.0"

def init_iscsi():
    logging.info("Инициализация iSCSI Target сервиса")
    
    if os.system("which tgtadm > /dev/null 2>&1") != 0:
        logging.error("tgt не установлен. Установите с помощью apt install tgt")
        sys.exit(1)
    
    run_cmd(["systemctl", "enable", "tgt"], check=False)
    run_cmd(["systemctl", "start", "tgt"], check=False)
    
    result = run_cmd(["systemctl", "status", "tgt"], check=False)
    if "Active: active" not in result.stdout:
        logging.warning("Сервис tgt не запущен. Попытка запустить...")
        run_cmd(["systemctl", "start", "tgt"], check=True)
    
    if os.system("which ufw > /dev/null 2>&1") == 0:
        run_cmd(["ufw", "allow", "3260/tcp"], check=False)
        logging.info("Открыт порт 3260 в ufw")

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

    backup_smb_conf()

    with open(SMB_CONF, "a") as f:
        f.write(f"\n[{share_name}]\n")
        f.write(f"  path = {share_path}\n")
        f.write("  read only = no\n")
        f.write("  writeable = yes\n")
        f.write(f"  valid users = {SMB_USER}\n")
        f.write("  # guest ok = no\n")
        f.write("  force create mode = 0775\n")
        f.write("  force directory mode = 0775\n")
        f.write(f"  force user = {SMB_USER}\n")
        f.write(f"  force group = {SMB_USER}\n")

    reload_smb_config()
    logging.info(f"SMB-шара {share_name} успешно добавлена и конфигурация перезагружена")

def create_iscsi_lun_dm(folder, snapshot_size="1G"):
    """
    Создает iSCSI LUN, используя LVM snapshot (Device Mapper) для зеркалирования данных.
    Требуется, чтобы данные overlayfs хранились на EXPORTS_LV.
    """
    target_name = f"{ISCSI_BASE_IQN}:{folder}"
    snapshot_name = f"snap_{folder}"
    snapshot_lv = f"/dev/vg0/{snapshot_name}"  # Подгоните под вашу группу томов

    logging.info(f"Создаем LVM snapshot {snapshot_lv} для тома {EXPORTS_LV}")
    # Создаем snapshot. Параметр --size определяет запас для копий при записи (copy-on-write)
    run_cmd(["lvcreate", "--size", snapshot_size, "--snapshot", "--name", snapshot_name, EXPORTS_LV], check=True)
    logging.info(f"LVM snapshot {snapshot_lv} успешно создан")

    # Определяем следующий свободный TID
    result = run_cmd(["tgtadm", "--mode", "target", "--op", "show"], check=False)
    target_ids = []
    for line in result.stdout.splitlines():
        if line.startswith("Target"):
            parts = line.split()
            if len(parts) > 1:
                tid_str = parts[1].rstrip(':')
                try:
                    tid = int(tid_str)
                    target_ids.append(tid)
                except ValueError:
                    logging.error(f"Не удалось преобразовать TID в число: {tid_str}")
    next_tid = 1
    if target_ids:
        next_tid = max(target_ids) + 1

    # Создаем новый iSCSI Target
    run_cmd(["tgtadm", "--mode", "target", "--op", "new", "--tid", str(next_tid), "--lld", "iscsi", "-T", target_name], check=True)
    logging.info(f"Создан iSCSI Target: {target_name} (TID: {next_tid})")
    
    # Добавляем LUN к Target, используя LVM snapshot как backing store
    run_cmd(["tgtadm", "--mode", "logicalunit", "--op", "new", "--tid", str(next_tid), "--lun", "1", "--backing-store", snapshot_lv], check=True)
    logging.info(f"Добавлен LUN 1 к target {target_name} с backing store {snapshot_lv}")
    
    run_cmd(["tgtadm", "--mode", "target", "--op", "bind", "--tid", str(next_tid), "--initiator-address", "ALL"], check=True)
    logging.info(f"Разрешены все подключения к target {target_name}")
    
    run_cmd("tgt-admin --dump > /etc/tgt/conf.d/targets.conf", shell=True, check=False)
    
    server_ip = get_server_ip()
    
    return {
        "target_name": target_name,
        "tid": next_tid,
        "server_ip": server_ip,
        "portal": f"{server_ip}:3260",
        "connect_command": f"iscsiadm --mode discovery --type sendtargets --portal {server_ip}:3260"
    }

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

    start_idx = lines.index(share_header)
    end_idx = start_idx + 1
    while end_idx < len(lines) and not lines[end_idx].startswith('['):
        end_idx += 1

    del lines[start_idx:end_idx]

    backup_smb_conf()

    with open(SMB_CONF, "w") as f:
        f.writelines(lines)

    reload_smb_config()
    logging.info(f"SMB-шара {share_name} успешно удалена из {SMB_CONF} и конфигурация перезагружена")

def remove_iscsi_target(folder, tid=None):
    """Удаляет iSCSI target по имени или TID"""
    target_name = f"{ISCSI_BASE_IQN}:{folder}"
    
    logging.info(f"Удаляем iSCSI Target: {target_name}")
    
    if tid is None:
        result = run_cmd(["tgtadm", "--mode", "target", "--op", "show"], check=False)
        for line in result.stdout.splitlines():
            if line.startswith("Target") and target_name in line:
                parts = line.split()
                if len(parts) > 1:
                    tid_str = parts[1].rstrip(':')
                    try:
                        tid = int(tid_str)
                    except ValueError:
                        logging.error(f"Не удалось преобразовать TID в число: {tid_str}")
                break
    
    if tid:
        try:
            run_cmd(["tgtadm", "--mode", "target", "--op", "unbind", "--tid", str(tid), "--initiator-address", "ALL"], check=False)
        except:
            pass
        
        run_cmd(["tgtadm", "--mode", "target", "--op", "delete", "--tid", str(tid), "--force"], check=False)
        logging.info(f"iSCSI Target TID {tid} успешно удален")
    else:
        logging.warning(f"Не удалось найти TID для target {target_name}")
    
    run_cmd("tgt-admin --dump > /etc/tgt/conf.d/targets.conf", shell=True, check=False)

def setup_env():
    ensure_packages()
    setup_lowerdir()
    init_smb()
    init_iscsi()

def create_overlay_mount(folder):
    lower_dir = LOWER_DIR
    upper_dir = os.path.join(EXPORTS_ROOT, folder, "upper")
    work_dir = os.path.join(EXPORTS_ROOT, folder, "work")
    merge_dir = os.path.join(EXPORTS_ROOT, folder, "merged")

    os.makedirs(EXPORTS_ROOT, exist_ok=True)
    os.makedirs(os.path.join(EXPORTS_ROOT, folder), exist_ok=True)
    os.makedirs(upper_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(merge_dir, exist_ok=True)

    try:
        user_info = pwd.getpwnam(SMB_USER)
        group_info = grp.getgrnam(SMB_USER)
    except KeyError:
        logging.error(f"Пользователь или группа '{SMB_USER}' не найдены.")
        sys.exit(1)

    for directory in [upper_dir, work_dir, merge_dir]:
        os.chown(directory, user_info.pw_uid, group_info.gr_gid)
        os.chmod(directory, 0o775)

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
    iscsi_size = data.get("iscsi_size", 1024)
    
    if not folder:
        folder = "r" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))

    try:
        create_overlay_mount(folder)
        # Для создания iSCSI тома с live-отображением данных через Device Mapper
        iscsi_info = create_iscsi_lun_dm(folder)
        
        expiration_time = datetime.datetime.utcnow() + datetime.timedelta(hours=12)
        folders_table.insert({
            'folder': folder,
            'expiration': expiration_time.timestamp(),
            'iscsi_info': iscsi_info,
            'iscsi_tid': iscsi_info['tid']
        })
        
        return jsonify({
            "status": "ok", 
            "folder": folder, 
            "smb_share": folder, 
            "iscsi_target": iscsi_info['target_name'],
            "iscsi_portal": iscsi_info['portal'],
            "iscsi_connection_info": {
                "Windows Command": f"iscsicli QAddTargetPortal {iscsi_info['server_ip']} && iscsicli QAddTarget {iscsi_info['target_name']} {iscsi_info['server_ip']}",
                "Linux Command": f"iscsiadm --mode discovery -t sendtargets --portal {iscsi_info['server_ip']}:3260 && iscsiadm --mode node --targetname {iscsi_info['target_name']} --portal {iscsi_info['server_ip']}:3260 --login"
            }
        }), 200
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
                iscsi_disk = os.path.join(EXPORTS_ROOT, folder, "iscsi_disk.img")

                run_cmd(["umount", merged_path], check=False)
                remove_smb_share(folder)
                tid = entry.get('iscsi_tid')
                remove_iscsi_target(folder, tid)
                
                folder_path = os.path.join(EXPORTS_ROOT, folder)
                if os.path.exists(folder_path):
                    run_cmd(["rm", "-rf", folder_path], check=False)

                folders_table.remove(Folder.folder == folder)
                logging.info(f"Папка {folder} успешно удалена")
        except Exception as e:
            logging.error(f"Ошибка в alina_thread: {e}")

        time.sleep(60)

@app.route("/status", methods=["GET"])
def get_status():
    try:
        Folder = Query()
        all_folders = folders_table.all()
        
        shares = []
        for entry in all_folders:
            expiry_time = datetime.datetime.fromtimestamp(entry['expiration'])
            remaining = (expiry_time - datetime.datetime.utcnow()).total_seconds() / 3600
            
            iscsi_info = entry.get('iscsi_info', {})
            if not iscsi_info and 'iscsi_tid' in entry:
                target_name = f"{ISCSI_BASE_IQN}:{entry['folder']}"
                server_ip = get_server_ip()
                iscsi_info = {
                    "target_name": target_name,
                    "tid": entry['iscsi_tid'],
                    "server_ip": server_ip,
                    "portal": f"{server_ip}:3260"
                }
            
            shares.append({
                "folder": entry['folder'],
                "smb_share": entry['folder'],
                "iscsi_target": iscsi_info.get('target_name', f"{ISCSI_BASE_IQN}:{entry['folder']}"),
                "iscsi_portal": iscsi_info.get('portal', 'unknown'),
                "expiry": expiry_time.strftime("%Y-%m-%d %H:%M:%S"),
                "remaining_hours": round(remaining, 1)
            })
        
        result = run_cmd(["tgtadm", "--mode", "target", "--op", "show"], check=False)
        
        return jsonify({
            "status": "ok",
            "shares": shares,
            "total": len(shares),
            "iscsi_system_status": result.stdout if hasattr(result, 'stdout') else "Недоступно"
        }), 200
    except Exception as e:
        logging.error(f"Ошибка при получении статуса: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/extend", methods=["POST"])
def extend_folder():
    data = request.get_json(force=True, silent=True) or {}
    folder = data.get("folder")
    hours = data.get("hours", 12)
    
    if not folder:
        return jsonify({"status": "error", "error": "Не указано имя папки"}), 400
    
    try:
        Folder = Query()
        folder_data = folders_table.get(Folder.folder == folder)
        
        if not folder_data:
            return jsonify({"status": "error", "error": f"Папка {folder} не найдена"}), 404
        
        current_expiry = datetime.datetime.fromtimestamp(folder_data['expiration'])
        new_expiry = current_expiry + datetime.timedelta(hours=hours)
        
        folders_table.update({'expiration': new_expiry.timestamp()}, Folder.folder == folder)
        
        return jsonify({
            "status": "ok", 
            "folder": folder,
            "new_expiry": new_expiry.strftime("%Y-%m-%d %H:%M:%S")
        }), 200
    except Exception as e:
        logging.error(f"Ошибка при продлении папки {folder}: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500

def main():
    parser = argparse.ArgumentParser(description="Настраивает OverlayFS + SMB + iSCSI окружение и запускает Flask API.")
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
