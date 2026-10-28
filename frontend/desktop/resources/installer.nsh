!macro customInstall
  ; Agent Desktop：安装完成后不自动启动（避免与开发态实例冲突）
  WriteRegExpandStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "AgentDesktop" '"$INSTDIR\Agent Desktop.exe" --minimized'
!macroend

!macro customUnInstall
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "AgentDesktop"
  ; 用户数据默认保留（与 deleteAppDataOnUninstall: false 一致）
!macroend
