# DT80 Control Studio

A Python desktop GUI application for operating DT80/DT8x data loggers through **USB Serial COM** or **Ethernet TCP/IP**.  
The goal of this project is to replace manual command typing with a clean button-based interface for jobs, logging, data export, alarms, files, startup settings, and diagnostics.

---

# Project Overview

DT80 Control Studio allows users to interact with a DT80/DT8x data logger using a graphical interface instead of typing commands manually into a terminal.

The application sends DT80 text commands internally when the user clicks buttons or fills forms. This makes common operations easier, safer, and more user-friendly.

---

# Main Features

## Connection Options

- Serial COM connection for USB/RS232 use
- Ethernet TCP/IP connection
- Console output for sent and received DT80 responses

---

## Operator Panel

- View device status
- Show current job
- Start and stop logging
- Start and halt schedules
- Run stored jobs

---

## Job Management

- Refresh stored job list
- Run selected job
- View job program using `SHOWPROG`
- Lock and unlock jobs
- Delete selected jobs
- Unlock all jobs
- Delete all jobs with confirmation

---

## Job Builder

- Create DT80 jobs using form inputs
- Add channel definitions
- Add schedule definitions
- Generate `BEGIN ... END` job text
- Upload jobs to the logger
- Optionally run the job after upload
- Optionally start logging and schedules after upload

---

## Data Tools

- List available logged data using `LISTD`
- Build `COPYD` commands using a guided wizard
- Export data to PC using stream mode
- Export data to internal memory or USB
- Build and confirm `DELD` delete commands
- Cancel unload using `Q`

---

## Startup and USB Tools

- Set startup job behavior
- Generate serial-specific ONINSERT file
- Generate global ONINSERT file
- Delete ONINSERT files

---

## File Manager

- Browse internal storage using `DIR`
- Browse USB storage using `DIR A:\`
- View text files using `TYPE`

---

## Diagnostics

- View version
- View serial number
- View date/time
- View memory/profile information
- Set device time/date

---

## Alarm Panel

- Show alarms
- Acknowledge alarms
- Clear alarms with confirmation

---

# Technology Stack

- Python
- PySide6
- pyserial
- socket programming
- DT80/DT8x command interface

---

# Project Structure

```text
dt80-control-studio/
│
├── app.py
├── ui_main.py
│
├── dt80/
│   ├── __init__.py
│   ├── transport.py
│   ├── client.py
│   ├── command_catalog.py
│   └── job_builder.py
│
└── README.md
```

---

# Installation

Clone the repository:

```bash
git clone https://github.com/YOUR_USERNAME/DT80-Control-Studio.git
cd DT80-Control-Studio
```

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it:

### Windows

```bash
.venv\Scripts\activate
```

### Linux / macOS

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install pyside6 pyserial
```

Run the application:

```bash
python app.py
```

---

# Connection Guide

## Serial / USB Mode

Use this when the DT80 appears as a COM port.

1. Connect DT80 to the computer using USB or serial
2. Open Device Manager
3. Check the assigned COM port (example: `COM5`)
4. Select **Serial (COM)** in the app
5. Enter the COM port and baud rate
6. Click **Connect**

---

## Ethernet Mode

Use this when the DT80 is connected through network.

1. Connect DT80 to the network
2. Confirm the IP address
3. Select **Ethernet (TCP/IP)** in the app
4. Enter the DT80 IP address
5. Use TCP port `7700`
6. Click **Connect**

---

# Important DT80 Commands Used Internally

| Feature | DT80 Command |
|---|---|
| Status | `STATUS` |
| Current job | `CURJOB` |
| List jobs | `DIRJOBS` |
| Run job | `RUNJOB "JobName"` |
| Show job program | `SHOWPROG "JobName"` |
| Start logging | `LOGON` |
| Stop logging | `LOGOFF` |
| Start schedules | `G` |
| Stop schedules | `H` |
| List data | `LISTD` |
| Export data | `COPYD` |
| Delete data | `DELD` |
| Cancel unload | `Q` |
| Lock job | `LOCKJOB` |
| Unlock job | `UNLOCKJOB` |
| Delete job | `DELJOB` |
| Delete all jobs | `DELALLJOBS` |
| Directory listing | `DIR` |
| View file | `TYPE` |
| Alarm list | `ALARMS` |
| Acknowledge alarms | `ACKALARMS` |
| Clear alarms | `CLEARALARMS` |

---

# Safety Notes

This application includes confirmation dialogs for destructive actions such as:

- Deleting jobs
- Deleting all jobs
- Deleting logged data
- Clearing alarms
- Reset-related actions

However, users should still test carefully on a non-critical DT80 device before using the app in a live environment.

---

# Current Status

This project is currently a working prototype.

Most core DT80 operations have been implemented through GUI buttons and guided forms.

Some commands may require final validation on a physical DT80/DT8x device because response formatting can vary depending on firmware, model, and configuration.

---

# Known Limitations

- LISTD parsing may need adjustment after testing with real hardware
- COPYD stream export may require tuning for very large data exports
- Some advanced profile, networking, and calibration features are not fully implemented yet
- Date/time command formatting should be validated against the exact DT80 model firmware
- UI updates from threaded command callbacks may need signal-based refinement for production use

---

# Future Improvements

- Safer Qt signal-based output handling
- Better LISTD parser
- Live data monitoring tab
- Real-time plotting
- Job export to PC
- Job import from PC
- Advanced file copy/delete tools
- Network configuration panel
- Packaged Windows `.exe` release
- Installer build
- User roles:
  - Operator
  - Technician
  - Admin

---

# Packaging as EXE

The app can later be packaged as a Windows executable using PyInstaller.

Install PyInstaller:

```bash
pip install pyinstaller
```

Build executable:

```bash
pyinstaller --onefile --windowed app.py
```

The generated executable will appear in the `dist/` folder.

---

# Example Screens

You can later add screenshots like:

```md
![Main Window](screenshots/main_window.png)
![Job Builder](screenshots/job_builder.png)
![Data Export](screenshots/data_export.png)
```

---

# Disclaimer

This is an independent student/developer project for controlling DT80/DT8x data loggers through their command interface.

It is not an official DataTaker product.

Use carefully and verify all commands on a test device before using in production.

---

# Author

Developed by Redwan Ibney Hasan using Python and PySide6.
