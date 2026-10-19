@echo off
setlocal EnableDelayedExpansion
set "MESSAGE=starting"
echo %MESSAGE%
for /l %%N in (3,-1,1) do (
set "CURRENT=%%N"
echo count=!CURRENT!
)
endlocal
echo done
