# DelimitationToolbox
A QGIS plugin containing various GIS Tools for electoral delimitation. Features include
- insertion of attributes from CSV to ESRI Shapefile
- Generation of Google Earth KMZ file
- Styling of KML file
- GUI for electoral constituency rebalancing using [Tindak Malaysia's](http://www.tindakmalaysia.org "Tindak Malaysia's homepage") method of equalisation


## Dependencies
The plugin requires at QGIS **2.0 or above** and is dependent on the following additional modules

- lxml
- python-win32  (windows only)



## Installation
Install QGIS using the OSGEO4W installer. Select the modules **qgis** and **qgis-full** under the Desktop category and install any dependencies specified by the installer. All necessary modules except for **lxml** will be installed.

#### For linux and OSX platforms:
You will just need to install the **lxml** module either using pip or easy_install.

#### For windows:
The easiest method of installing the dependencies is to install the **python-win32** module via the OSGE4W installer. The precompiled binaries for the **lxml** module is available athttp://www.lfd.uci.edu/~gohlke/pythonlibs/#lxml. Depending on the whether you've installed the 32-bit or 64-bit of QGIS, the files to download are [lxml-3.3.6.win-amd64-py2.7.exe (64-bit)](http://www.lfd.uci.edu/~gohlke/pythonlibs/ansi47vi/lxml-3.3.6.win-amd64-py2.7.exe) or [lxml-3.3.6.win32-py2.7.exe (32-bit)](http://www.lfd.uci.edu/~gohlke/pythonlibs/ansi47vi/lxml-3.3.6.win32-py2.7.exe).

Then open an OSGEO4W shell and use **easy_install** to install the downloaded lxml module, by issuing the following command
> easy_install location-of-the-downloaded-lxml.exe-file

If **easy_install** is not found, download the file [get-pip.py](https://bootstrap.pypa.io/get-pip.py) and install it, by executing the following command in the OSGEO4W Shell first
> python get-pip.py

##Feedback
Any feedback or suggestion would be much greatly appreciated.
