# VerticalTimeline

A Fusion 360 add-in that adds vertical timeline.

![](screenshot.png)

## Installation
Drop the files in `%appdata%\Autodesk\Autodesk Fusion 360\API\AddIns` .

Make sure the directory is named `VerticalTimeline`, with no suffix.

Press Shift+S in Fusion 360 and go to the *Add-Ins* tab. Then select the add-in and click the *Run* button. Optionally select *Run on Startup*.

## Usage

The timeline is shown using *File* -> *View* -> *Toggle Vertical Timeline*.

* Click an item to select it*.
* Double-click on an item to edit it*.
* Click on an item text to rename it.
* Right click an item to roll to it.

 \* See TODO.

## TODO

* Improve performance

* Fix nested coloring not reused in new documents.

* Highlight feature selected in the Fusion GUI.

* Less intrusive error messages.

* Fix broken functionality once Fusion fixes its bugs

  * Cannot show all feature images due to bug: [[API BUG] Cannot access entity of "Move" feature](https://forums.autodesk.com/t5/fusion-360-api-and-scripts/api-bug-cannot-access-entity-of-quot-move-quot-feature/m-p/9651921)

  * Workaround for document switching since documentActivated is broken. [[API BUG] Application.documentActivated Event do not raise](https://forums.autodesk.com/t5/fusion-360-api-and-scripts/api-bug-application-documentactivated-event-do-not-raise/m-p/9020750)

  * Cannot select features that belong to components: [Cannot select object in component using activeSelections](https://forums.autodesk.com/t5/fusion-360-api-and-scripts/cannot-select-object-in-component-using-activeselections/m-p/9653216)

    
