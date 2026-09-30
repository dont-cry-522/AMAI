"""Personal portable launcher: discover classic Warcraft, install and connect."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import bridge

EXECUTABLES=('war3.exe','Frozen Throne.exe','Warcraft III.exe')
SKIP={'windows','programdata','$recycle.bin','system volume information','node_modules',
      '.git','.venv','__pycache__','appdata','winsxs','runtime'}


def game_executable(folder):
    # Classic installs have Game.dll and MPQ data; avoid selecting modern launchers.
    folder=Path(folder)
    if not (folder/'Game.dll').is_file() or not any((folder/n).is_file() for n in ('war3.mpq','war3x.mpq')):
        return None
    return next((folder/n for n in EXECUTABLES if (folder/n).is_file()),None)


def find_games(roots,seconds=45):
    found=set()
    deadline=time.monotonic()+seconds
    for root in roots:
        for current,dirs,files in os.walk(root,followlinks=False):
            if time.monotonic()>deadline:
                return sorted(found)
            current=Path(current)
            dirs[:]=[d for d in dirs if d.lower() not in SKIP and not (current/d).is_junction()]
            if len(current.relative_to(root).parts)>=6:
                dirs.clear()
            names={f.lower() for f in files}
            if any(n.lower() in names for n in EXECUTABLES) and game_executable(current):
                found.add(current.resolve())
                dirs.clear()
    return sorted(found)


def registry_games():
    import winreg
    found=set()
    for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_32KEY,winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive,r'Software\Blizzard Entertainment\Warcraft III',0,winreg.KEY_READ|view) as key:
                    for name in ('InstallPath','InstallPathX'):
                        try:
                            value=winreg.QueryValueEx(key,name)[0]
                            path=Path(os.path.expandvars(value.strip('"')))
                            if game_executable(path):
                                found.add(path.resolve())
                        except (OSError,TypeError,AttributeError):
                            pass
            except OSError:
                pass
    return sorted(found)


def pick_game(candidates):
    if len(candidates)==1:
        return candidates[0]
    print('发现多个魔兽版本，请选平时玩的程序。' if candidates else '未能自动找到魔兽，请在窗口中选一次游戏程序。',flush=True)
    # Built-in Windows picker; the bundled Python intentionally has no GUI dependency.
    script="""Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = '选择你平时玩的魔兽争霸3经典版程序'
$dialog.Filter = 'Warcraft III|war3.exe;Frozen Throne.exe;Warcraft III.exe'
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Write($dialog.FileName) }
"""
    result=subprocess.run(['powershell.exe','-NoProfile','-STA','-Command',script],
                          capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    selected=result.stdout.decode('utf-8-sig').strip()
    if result.returncode or not selected:
        raise ValueError('未选择游戏，已退出；接口配置已经保存，无需重填。')
    game=Path(selected).parent.resolve()
    if not game_executable(game):
        raise ValueError('所选程序不属于可识别的经典版游戏目录。')
    return game


def discover_game(config,explicit=None):
    if explicit:
        path=Path(explicit).resolve()
        path=path.parent if path.is_file() else path
        if not game_executable(path):
            raise ValueError('拖入的文件夹不是经典版魔兽目录。')
        return path
    saved=config.get('game_dir','')
    if saved and game_executable(saved):
        return Path(saved).resolve()
    registered=registry_games()
    if registered:
        return pick_game(registered)
    nearby=[bridge.ROOT,bridge.ROOT.parent,bridge.ROOT.parent.parent]
    common=[]
    drives=[]
    for letter in 'CDEFGHIJKLMNOPQRSTUVWXYZ':
        drive=Path(letter+':\\')
        if ctypes.windll.kernel32.GetDriveTypeW(str(drive))==3:
            drives.append(drive)
            for name in ('Warcraft III','Warcraft3','War3','魔兽争霸3','Games/Warcraft III','Games/Warcraft3',
                         '游戏/魔兽争霸3','Program Files (x86)/Warcraft III','Program Files/Warcraft III'):
                common.append(drive/name)
    candidates=sorted({p.resolve() for p in nearby+common if game_executable(p)})
    if candidates:
        return pick_game(candidates)
    print('正在自动查找魔兽，最多约 45 秒……',flush=True)
    # Search data disks first; skip OS/cache trees and directory junctions.
    drives.sort(key=lambda p:str(p).lower().startswith('c:'))
    return pick_game(find_games(drives))


def main():
    if not bridge.CONFIG.is_file():
        raise ValueError('缺少私人配置文件，请完整复制并解压私人包。')
    config=json.loads(bridge.CONFIG.read_text(encoding='utf-8'))
    if not config.get('api_key'):
        raise ValueError('此包没有预置模型密钥，请使用已配好的私人包。')
    game=discover_game(config,sys.argv[1] if len(sys.argv)>1 else None)
    print('已找到魔兽：'+str(game),flush=True)
    bridge.install_game(game)
    config['game_dir']=str(game)
    bridge.atomic_write(bridge.CONFIG,json.dumps(config,ensure_ascii=False,indent=2))
    print('配置完成。进入单人自定义游戏，选 AMAI_DeepSeek（普通版）或 AMAI_DeepSeek_Voice（语音版）里的海龟岛。',flush=True)
    print('两版使用相同的 DeepSeek 指挥；语音版开局后准备 F7 说话，无需切换连接程序。',flush=True)
    print('一个真人加三个电脑，分成 2 对 2，选择指挥模式。保持本窗口开启。',flush=True)
    # Do not start another copy of the game when it is already open.
    running=subprocess.run(['tasklist.exe','/FO','CSV','/NH'],capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW).stdout.lower()
    if not any(('"'+n+'"').encode('ascii').lower() in running for n in EXECUTABLES):
        subprocess.Popen([str(game_executable(game))],cwd=game)
    else:
        print('游戏已运行；如果刚启用本地读取，请退出游戏后重新打开。',flush=True)
    bridge.run_bridge(config)


if __name__=='__main__':
    try:
        main()
    except Exception as e:
        print('未能启动：'+(str(e) if isinstance(e,ValueError) else type(e).__name__),flush=True)
        raise SystemExit(1)
