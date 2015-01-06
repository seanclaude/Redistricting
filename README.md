# Redistricting for QGIS
A QGIS plugin to assist in the the electoral delineation process. It provides a GUI interface to enable people in a 
democracy (or for those who are fighting to achieve democracy) to come up with their own alternative maps. 
The plugin was created for [Tindak Malaysia](http://www.tindakmalaysia.org "Tindak Malaysia") in preparation for the Malaysian 2015 Delimitation exercise.

## Dependencies
The plugin requires at least [QGIS](http://www.qgis.org "QGIS") **2.4 or above**. There are no dependencies. Just install the plugin from within QGIS.


## Issues/Problems/Bugs
If you find a problem, please submit an issue report. Either include the stackdump or explain how the problem can be reproduced to help with the troubleshooting.

##Feedback
Any feedback or suggestion would be greatly appreciated.


Background
==========
This plugin was created to anticipate the need to equalise constituencies throughout Malaysia quickly if the delimitation
proposal by the Malaysian Election Commission is found to be unfair in terms of malapportionment and the occurance of gerrymandering.

What this plugin does is to present the necessary information (polling districts and the number of voters) to allow
a user to quickly equalise both parliament and state constituencies in a Malaysian state simultaneously without
the need to increase the number of political seats (constituencies).

As a plugin in QGIS, it allows other layers to be loaded to provide additional information.

The plugin is released under the open-source GPLv2 license.


Requirements
============
Supported file formats
----------------------
The plugin works with vector layers stored in Shapefiles and PostGIS database vector layers.

Loading Layers
--------------
Using QGIS, load the file you want to analyse via **Layer -> Add Vector Layer …**. This shapefile should contain the
state map with individual polling districts as vector polygons (features).

Alternatively, you can drag and drop the shapefile onto QGIS to load it. You may however need to set the layer CRS
appropriately as QGIS sometimes fail to correctly identify the CRS.

A mercator projection is required for area calculations to work properly.

Attribute Table
---------------
Each feature (polling district) can hold additional data about it. These are stored in the attribute table.
For the plugin, the attribute table must contain at least the following fields

-  3 text attribute fields to store the unique IDs for the **old/current parliamentary and state seats as well
   as the polling district**

-  3 text attribute fields to store the unique IDs for the **new or proposed parliamentary and state seats as well
   as the polling district**

-  An integer field for storing the **number of voters** in each polling district

The included shapefile for the Malaysian state of Perlis provides an example of the required attribute fields

-  Old/current constituencies: parlama (parliament), dunlama (state), dmlama (polling district)

-  New/proposed constituencies: parbaru (parliament), dunbaru (state), dmbaru (polling district)

-  Number of voters: pengundi


Plugin Interface
================
The following gives a brief overview of the user interface. Additionally, if you hover your mouse over certain UI elements,
there will be tool tips to explain what each element does.

Map Colours
-----------
The different colours gives the following information.

-  Grey - Constituency is within the specified EQ

-  Blue - Constituency is more than 10% (EQ) smaller than the average constituency size

-  Red - Constituency is more than 10% (EQ) larger than the average constituency size 


The different shades are used for identifying the different state (STATE) or parliamentary (PAR) constituencies.
**Currently, they do not represent size, ie. a constituency with a deeper shade of blue does not mean it is
smaller than one that is lighter. **

**TIP:** You can press the **refresh map** button repeatedly to redraw the layer with a slightly different shade.

Interface Tabs
==============
Constituencies
--------------
To get a list of PARs and STATEs sizes, select the constituency tab and click list constituencies.
You can click on each row to highlight the selected state constituency. Each column is sortable by clicking on the
column title.


EQ Tab
------
Right clicking on a feature will switch you to the EQ tab and display the appropriate dropdown values, giving you details of
the parliamentary and state constituencies it belongs to.

**While equalising, you will spend most of your time here.**

**TIP:** Right click on features in constituencies around the constituency you want to update to quickly identify small or large
constituencies when equalising. For example, a smaller neighbouring constituency means you can move polling districts to it from oversized
constituencies. While a larger neighbour means you can take polling districts from it to be allocated to undersized constituencies.

While equalising, we may wish to have access to additional information like natural boundaries like roads, rivers and administrative
boundaries. These layers can be loaded in QGIS and layered on top of your working layer.


Plugin Operation
================
The following mouse actions are possible when the plugin is started

 - Left-click - Select/Unselect a feature
 
 - Right-click - Get details of parliamentary/state constituency the polling district is currently in
 
 - Right click and hold - Pan map
 
 - Left click and hold - Multi select
 
 - Double right click - Select/Unselect the entire parliamentary constituency
 
 - Double left click - Select/Unselect the entire state constituency

You can change the various dropdown options to switch between old and new maps or whether you want to balance state or parliamentary
constituencies.

Press the refresh map button to redraw the map based on the selected choices.

Feature labels
--------------
Each feature has a label, which can be turned on and off. For example,

-  **1/1/03** corresponds to the values **parliamentary ID/state ID/polling district ID**

-  **10.78** is the relative size of the polling districts in percentage. No. of voters/average constituency voters. Constituency here may mean state or parliamentary.

Equalisation/Rebalancing
------------------------
To achieve equalisation of voters across constituencies, a user can either start with a clean map or redistrict based on the existing map.

To redistrict based on the existing map, use the "copy old map” button to copy the old/current ID values over to the new ID fields.

To redistrict from a clean map, use the "reset new map" button.

**All updates will write to the vector layer directly. BUT only the 3 new ID fields will be affected.**


Clean Start Tips
----------------
Start by allocating state constituencies until equalisation is reached.

Existing Start Tips
-------------------
In this scenario, we first equalise the parliamentary constituencies. Then, equalise state constituencies by only 
moving polling districts among the state constituencies within a parliamentary.

**TIP:**

1. Try using a smaller EQ to help identify oversized and undersized constituencies, eg. Try using 5% even though your goal is 10%. The plugin will help highlight outliers quickly.

2. If you’re blocked by very large polling districts, try to see if you can swap large polling districts so that the nett change is small.

3. If the recommendation engine suggests that you need to add more state seats, try reducing the size of your parliamentary constituency.
   Change your EQ to a tighter value to identify constituencies that you can shift polling districts too.


Moving Polling Districts
------------------------
The most basic operation that we need to know is how to allocate a polling district to a constituency. This involves 2 things

-  specifying the PAR and STATE IDs that we want to update
-  selecting features to write these IDs to

**If a PAR or STATE ID is currently unassigned, it will be highlighted green in the dropdown list.**

To assign a polling district to another constituency, do the following

1.  Right click on any feature on the map to switch focus to it. The EQ tab will be displayed when you do this. 

2.  Left-click on a feature or features that we wish to move to select it

3.  The target constituency where you wish to move your selected constituencies should be shown by the dropdown selectors.
If it doesn't show the constituency that you wish to move your selection to, right click on a feature within the target constituency.

4.  Click the button **write selected** to confirm the move.


Renumbering
===========
When viewing the new map, you may have noticed that the feature ID does not display the polling district ID. 
This is because it is not relevant during equalising. This will only become a concern when exporting,
printing or sharing your equalised map.


The **resequence new map** button is what you need to click. It helps regenerate the IDs of the new parliamentary, state and polling
districts for you.

This is useful when the numbering for your constituencies are not ordered correctly. This will help you to save time during the
equalisation process as you no longer have to concern yourself with getting the ordering right.


Equalisation Metrics
====================
Although some constitution only recommends that sizes of constituencies be roughly equal, there is also the concern of human bias that plays a
big part in unfair delineations.

Circularity
-----------
To try achieve a roundish shape if possible. If a constituency has a very low circularity score, there is a high possibility that it is being gerrymandered.
The exception will be for situations where the constituency is restricted by natural boundaries like mountain ranges or rivers leading
to it having a strange snaky shape.

Area size
---------
If you’re constituency is too large to be easily accessible then you may want to consider swapping some large polling districts for a smaller
polling district with a higher voter count. 

