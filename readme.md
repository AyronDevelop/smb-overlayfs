# Samba OverlayFS Manager

## English Version

### Table of Contents
- [Description](#description)
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Security Considerations](#security-considerations)
- [Example](#example)
- [Troubleshooting](#troubleshooting)
- [License](#license)

### Description

**Samba OverlayFS Manager** is a Python-based tool that automates the setup of OverlayFS combined with Samba shares. It allows dynamic creation of network shares via a Flask API, facilitating easy management of shared directories with read and write permissions.

### Features

- **Automated Setup**: Installs necessary packages and configures Samba.
- **Dynamic Share Creation**: Create new Samba shares on-the-fly using RESTful API endpoints.
- **OverlayFS Integration**: Combines lower and upper directories to manage file versions.
- **User Management**: Configures Samba to use a specified system user for file operations.
- **Secure Access**: Restricts share access to authenticated Samba users.

### Requirements

- **Operating System**: Debian-based Linux distribution (e.g., Ubuntu, Debian)
- **Python**: Python 3.x
- **Privileges**: Root (sudo) access
- **Network**: Accessible network for Samba shares

### Installation

1. **Clone the Repository**

    ```bash
    git clone https://github.com/yourusername/samba-overlayfs-manager.git
    cd samba-overlayfs-manager
    ```

2. **Ensure the Script is Executable**

    ```bash
    chmod +x samba_overlayfs_manager.py
    ```

3. **Run the Script as Root**

    ```bash
    sudo python3 samba_overlayfs_manager.py --port 5000
    ```

    The script will:
    - Install required packages (`samba`, `python3-pip`, `rsync`)
    - Install Python dependencies (`flask`)
    - Configure and restart the Samba service
    - Set up necessary directories for OverlayFS

### Configuration

1. **Set Samba User**

    By default, the script uses the `root` user for Samba operations. **_Note:_** Using `root` is **not recommended** due to security risks. It is advisable to use a dedicated user with limited permissions.

    To create a new user and add it to Samba:

    ```bash
    sudo adduser sambauser
    sudo smbpasswd -a sambauser
    ```

2. **Modify the Script (Optional)**

    If you prefer to use a different user, update the `SMB_USER` variable in the script:

    ```python
    SMB_USER = "sambauser"
    ```

3. **Set Directory Paths**

    Ensure that the paths defined in the script (`LOWER_DIR`, `EXPORTS_ROOT`, `SMB_CONF`) are correct and accessible.

### Usage

1. **Start the Flask API**

    ```bash
    sudo python3 samba_overlayfs_manager.py --port 5000
    ```

    The Flask API will listen on the specified port (default: 5000).

2. **Create a New Samba Share**

    Send a POST request to the `/create_folder` endpoint to create a new share.

    **Using `curl`:**

    ```bash
    curl -X POST http://localhost:5000/create_folder
    ```

    **Response:**

    ```json
    {
      "status": "ok",
      "folder": "rand_xxxxxx"
    }
    ```

    This will create a new OverlayFS mount and corresponding Samba share named `rand_xxxxxx`.

3. **Access the Samba Share**

    From a Windows machine or any Samba client, connect to the share using the credentials of the specified Samba user.

    **Example:**

    ```
    \\your_server_ip\rand_xxxxxx
    ```

### Security Considerations

- **Avoid Using `root`**: Running Samba operations as `root` poses significant security risks. It's recommended to use a dedicated user with limited permissions.
- **Firewall Configuration**: Ensure that the necessary ports for Samba (usually TCP 445) and the Flask API are open and secured.
- **Strong Passwords**: Use strong, unique passwords for Samba users to prevent unauthorized access.
- **Regular Updates**: Keep your system and Samba packages up to date to mitigate security vulnerabilities.
- **Restrict API Access**: Limit access to the Flask API to trusted networks or implement authentication mechanisms.

### Example

1. **Create a Share via API**

    ```bash
    curl -X POST http://localhost:5000/create_folder
    ```

2. **Connect to the Share on Windows**

    - Open File Explorer.
    - Enter `\\your_server_ip\rand_xxxxxx` in the address bar.
    - Enter Samba credentials when prompted.

3. **Perform File Operations**

    - Create, modify, or delete files within the share as the authenticated Samba user.

### Troubleshooting

- **Permission Denied Errors**:
    - Ensure that the Samba user has the necessary permissions on the `LOWER_DIR` and OverlayFS directories.
    - Verify ownership and permissions using `ls -ld` on the relevant directories.

- **Samba Service Issues**:
    - Check Samba logs located at `/var/log/samba/` for detailed error messages.
    - Restart the Samba service:

      ```bash
      sudo systemctl restart smbd
      ```

- **API Not Responding**:
    - Ensure that the Flask API is running without errors.
    - Check for port conflicts or firewall restrictions.

### License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---

## Русская Версия

### Содержание
- [Описание](#описание)
- [Особенности](#особенности)
- [Требования](#требования)
- [Установка](#установка)
- [Настройка](#настройка)
- [Использование](#использование)
- [Соображения по безопасности](#соображения-по-безопасности)
- [Пример](#пример)
- [Устранение неполадок](#устранение-неполадок)
- [Лицензия](#лицензия)

### Описание

**Samba OverlayFS Manager** — это инструмент на основе Python, который автоматизирует настройку OverlayFS в сочетании с Samba-шарами. Он позволяет динамически создавать сетевые ресурсы через Flask API, облегчая управление общими директориями с правами на чтение и запись.

### Особенности

- **Автоматическая установка**: Устанавливает необходимые пакеты и настраивает Samba.
- **Динамическое создание шары**: Создавайте новые Samba-шары на лету с помощью RESTful API.
- **Интеграция с OverlayFS**: Объединяет нижние и верхние директории для управления версиями файлов.
- **Управление пользователями**: Настраивает Samba для использования указанного системного пользователя для операций с файлами.
- **Безопасный доступ**: Ограничивает доступ к шарам аутентифицированными пользователями Samba.

### Требования

- **Операционная система**: Linux-дистрибутив на основе Debian (например, Ubuntu, Debian)
- **Python**: Python 3.x
- **Права доступа**: Права суперпользователя (sudo)
- **Сеть**: Доступная сеть для Samba-шар

### Установка

1. **Клонирование репозитория**

    ```bash
    git clone https://github.com/yourusername/samba-overlayfs-manager.git
    cd samba-overlayfs-manager
    ```

2. **Убедитесь, что скрипт имеет права на выполнение**

    ```bash
    chmod +x samba_overlayfs_manager.py
    ```

3. **Запуск скрипта от имени root**

    ```bash
    sudo python3 samba_overlayfs_manager.py --port 5000
    ```

    Скрипт выполнит следующие действия:
    - Установит необходимые пакеты (`samba`, `python3-pip`, `rsync`)
    - Установит Python-зависимости (`flask`)
    - Настроит и перезапустит службу Samba
    - Создаст необходимые директории для OverlayFS

### Настройка

1. **Создание пользователя Samba**

    По умолчанию скрипт использует пользователя `root` для операций Samba. **_Примечание:_** Использование `root` **не рекомендуется** из-за рисков безопасности. Рекомендуется использовать специализированного пользователя с ограниченными правами.

    Для создания нового пользователя и добавления его в Samba:

    ```bash
    sudo adduser sambauser
    sudo smbpasswd -a sambauser
    ```

2. **Изменение скрипта (опционально)**

    Если вы предпочитаете использовать другого пользователя, обновите переменную `SMB_USER` в скрипте:

    ```python
    SMB_USER = "sambauser"
    ```

3. **Установка путей к директориям**

    Убедитесь, что пути, определённые в скрипте (`LOWER_DIR`, `EXPORTS_ROOT`, `SMB_CONF`), корректны и доступны.

### Использование

1. **Запуск Flask API**

    ```bash
    sudo python3 samba_overlayfs_manager.py --port 5000
    ```

    Flask API будет слушать на указанном порту (по умолчанию: 5000).

2. **Создание новой Samba-шары**

    Отправьте POST-запрос к эндпоинту `/create_folder` для создания новой шары.

    **Используя `curl`:**

    ```bash
    curl -X POST http://localhost:5000/create_folder
    ```

    **Ответ:**

    ```json
    {
      "status": "ok",
      "folder": "rand_xxxxxx"
    }
    ```

    Это создаст новый OverlayFS-монтирование и соответствующую Samba-шару с именем `rand_xxxxxx`.

3. **Доступ к Samba-шаре**

    С Windows-машины или любого Samba-клиента подключитесь к шаре, используя учётные данные указанного пользователя Samba.

    **Пример:**

    ```
    \\ip_вашего_сервера\rand_xxxxxx
    ```

### Соображения по безопасности

- **Избегайте использования `root`**: Использование пользователя `root` для операций Samba создаёт серьёзные риски безопасности. Рекомендуется использовать специализированного пользователя с ограниченными правами.
- **Настройка брандмауэра**: Убедитесь, что необходимые порты для Samba (обычно TCP 445) и Flask API открыты и защищены.
- **Надёжные пароли**: Используйте сложные, уникальные пароли для пользователей Samba, чтобы предотвратить несанкционированный доступ.
- **Регулярные обновления**: Держите систему и пакеты Samba в актуальном состоянии для устранения уязвимостей безопасности.
- **Ограничение доступа к API**: Ограничьте доступ к Flask API доверенными сетями или внедрите механизмы аутентификации.

### Пример

1. **Создание шары через API**

    ```bash
    curl -X POST http://localhost:5000/create_folder
    ```

2. **Подключение к шаре на Windows**

    - Откройте Проводник.
    - Введите `\\ip_вашего_сервера\rand_xxxxxx` в адресную строку.
    - Введите учётные данные Samba при запросе.

3. **Выполнение операций с файлами**

    Создавайте, изменяйте или удаляйте файлы внутри шары как аутентифицированный пользователь Samba.

### Устранение неполадок

- **Ошибки отказа в доступе**:
    - Убедитесь, что пользователь Samba имеет необходимые права на директории `LOWER_DIR` и OverlayFS.
    - Проверьте владение и права доступа с помощью команды `ls -ld` на соответствующих директориях.

- **Проблемы со службой Samba**:
    - Проверьте логи Samba, расположенные в `/var/log/samba/`, для получения подробных сообщений об ошибках.
    - Перезапустите службу Samba:

      ```bash
      sudo systemctl restart smbd
      ```

- **API не отвечает**:
    - Убедитесь, что Flask API запущен без ошибок.
    - Проверьте наличие конфликтов портов или ограничений брандмауэра.

### Лицензия

Этот проект лицензирован под лицензией MIT. Подробнее см. файл [LICENSE](LICENSE).

---
