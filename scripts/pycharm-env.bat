@echo off
SET OSGEO4W_ROOT=C:\OSGeo4W64


set path=%OSGEO4W_ROOT%\apps\qgis-ltr\bin;%OSGEO4W_ROOT%\bin;%WINDIR%\system32;%WINDIR%;%WINDIR%\system32\WBem

for %%F in ("%OSGEO4W_ROOT%\etc\ini\*.bat") do call "%%F"

call %OSGEO4W_ROOT%\bin\py3_env.bat
call %OSGEO4W_ROOT%\bin\qt5_env.bat

set QGIS_PREFIX_PATH=%OSGEO4W_ROOT:\=/%/apps/qgis-ltr
set GDAL_FILENAME_IS_UTF8=YES
rem Set VSI cache to be used as buffer, see #6448
set VSI_CACHE=TRUE
set VSI_CACHE_SIZE=1000000
set QT_PLUGIN_PATH=%OSGEO4W_ROOT%\apps\qgis-ltr\qtplugins;%OSGEO4W_ROOT%\apps\Qt5\plugins

REM for QGIS
set PYTHONPATH=%OSGEO4W_ROOT%\apps\qgis-ltr\python;%PYTHONPATH%

"C:\Program Files (x86)\JetBrains\PyCharm Community Edition 2020.1.3\bin\pycharm64.exe"