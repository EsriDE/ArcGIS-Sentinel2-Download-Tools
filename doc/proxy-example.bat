@echo on
:: Set environment variables for proxy server use, then start the affected process.

set ProxyServer=192.168.3.128
set ProxyPort=3128

:: If the proxy server use requires Basic Authorization, additionally set:
rem set MyUserNameAtProxy=JohnDoe
rem set MyPasswordAtProxy=VerySecret
:: To avoid revealing this text to other users, move this batch file to your personal user profile directory (i.e. %USERPROFILE%)!

set https_proxy=%MyUserNameAtProxy%:%MyPasswordAtProxy%@%ProxyServer%:%ProxyPort%
set http_proxy=%https_proxy%
@echo on
"C:\Program Files (x86)"\ArcGIS\Desktop10.5\bin\ArcMap.exe
