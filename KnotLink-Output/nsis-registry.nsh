; ============================================================
;  KnotLink 独立式节点 — NSIS 注册表头文件
;  用于 Schedule 4.0 安装包
; ============================================================
;  使用方式：
;    1. 将此文件放在 .nsi 同目录下
;    2. 在主 .nsi 中：!include "nsis-registry.nsh"
;    3. 在安装 Section 中调用：${KL_Register}
;    4. 在卸载 Section 中调用：${KL_Unregister}
; ============================================================

!define APP_ID "com.github.wenjin6470.schedule4"

; ---- 写入注册表（安装时调用）----
!macro KL_Register
  WriteRegStr HKCU "Software\KnotLink\StandaloneNodes" "${APP_ID}" "$INSTDIR"
!macroend

; ---- 清理注册表（卸载时调用）----
!macro KL_Unregister
  DeleteRegValue HKCU "Software\KnotLink\StandaloneNodes" "${APP_ID}"
!macroend
