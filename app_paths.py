"""
╔══════════════════════════════════════════════════════════════════════════╗
║        📅 电子课表系统 —— app_paths.py（路径解析统一入口）                ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的作用
═══════════════════════════════════════════════════════════════════════════
项目同时存在两种运行形态：
  1. 开发环境（Code/）：源码 + Config/ + images/ 与各 .py 同目录
  2. 打包环境（exe/）：main.exe + _internal/ + Config/ + images/ 并列

两种形态下，"程序根目录"的位置不同，而全项目有约 30 处代码用
  os.path.dirname(os.path.abspath(__file__))
来定位 Config/、images/、log/ 等资源目录。

打包后 __file__ 指向 _internal/ 内部（或 onefile 临时解压目录），
该路径旁并没有 Config/、images/ —— 必须统一改为 app_root()。

本模块提供两个函数：
  app_root()  —— 程序根目录（源码=Code/，打包=exe 所在目录）
  is_frozen() —— 是否运行在打包环境中（Nuitka / PyInstaller 通用）

⚠️ 本模块禁止 import 任何业务模块（schedule_*、PySide6），
   否则会造成循环导入或打包时的多余依赖。
"""

import os
import sys


def is_frozen() -> bool:
    """
    判断当前是否运行在"打包环境"中。
    ---------------------------------
    兼容 Nuitka / PyInstaller，不依赖单一标志：
      1. sys.frozen（PyInstaller 设置，Nuitka 部分版本也会设置）
      2. '__compiled__' in globals()（Nuitka 官方推荐，主模块有效）
      3. 兜底：本模块 __file__ 旁是否存在 main.py ——
         打包后 __file__ 位于 _internal/ 内，main.py 必然不存在；
         源码运行时 __file__ 就在 Code/ 下，main.py 必然存在。
    """
    if getattr(sys, 'frozen', False):
        return True
    if '__compiled__' in globals():
        return True
    script_dir: str = os.path.dirname(os.path.abspath(__file__))
    return not os.path.exists(os.path.join(script_dir, 'main.py'))


def app_root() -> str:
    """
    返回"程序根目录"（所有资源路径的基准目录）。
    ---------------------------------------------
      - 源码运行：Code/ 目录（__file__ 所在目录）
      - 打包运行：main.exe 所在目录（exe/ 部署目录）
    返回的是绝对路径，末尾不带分隔符。
    """
    if is_frozen():
        # 打包环境：exe 所在目录就是资源根目录
        return os.path.dirname(os.path.abspath(sys.executable))
    # 源码环境：本文件所在目录（= Code/）
    return os.path.dirname(os.path.abspath(__file__))
