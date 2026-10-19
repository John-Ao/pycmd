@echo off
cls
echo CMOS coordinate check
echo Click the dot with left mouse.
echo Expected: X=21 Y=8 P=21008
echo.
echo.
echo.
echo.
echo(                    .
echo.
cmos 0 -1 1 0 10
set "RAW=%errorlevel%"
set "P=%RAW%"
if "%P%"=="0" exit /b 1
if %P% lss 0 set /a P=-P
set /a "X=P/1000,Y=P%%1000"
echo Raw: [%RAW%]
echo X: [%X%]  Y: [%Y%]
echo Expected: [21] [8]
if %X% equ 21 if %Y% equ 8 (echo MATCH&exit /b 0)
echo MISMATCH
exit /b 1
