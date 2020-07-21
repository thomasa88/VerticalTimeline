#Author-Thomas Axelsson
#Description-Provides a vertical timeline.

import adsk.core, adsk.fusion, adsk.cam, traceback

import json
import os

# Event handler for the commandExecuted event.
class ShowPaletteCommandExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            # Create and display the palette.
            palette = ui.palettes.itemById('thomasa88-verticalTimelinePalette')
            if not palette:
                palette = ui.palettes.add('thomasa88-verticalTimelinePalette', 'Vertical Timeline', 'palette.html',
                                          True, True, True, 300, 500, False)
                palette.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateLeft
    
                # Add handler to HTMLEvent of the palette.
                onHTMLEvent = MyHTMLEventHandler()
                palette.incomingFromHTML.add(onHTMLEvent)   
                handlers.append(onHTMLEvent)
    
                # Add handler to CloseEvent of the palette.
                onClosed = MyCloseEventHandler()
                palette.closed.add(onClosed)
                handlers.append(onClosed)
            else:
                palette.isVisible = True                               
        except:
            ui.messageBox('Command executed Vertical Timeline failed: {}'.format(traceback.format_exc()))

# Event handler for the commandCreated event.
class ShowPaletteCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            command = args.command
            onExecute = ShowPaletteCommandExecuteHandler()
            command.execute.add(onExecute)
            handlers.append(onExecute)                                     
        except:
            ui.messageBox('Vertical Timeline failed:\n{}'.format(traceback.format_exc())) 

# Event handler for the palette close event.
class MyCloseEventHandler(adsk.core.UserInterfaceGeneralEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            pass
        except:
            ui.messageBox('Vertical Timeline failed:\n{}'.format(traceback.format_exc()))


# Event handler for the palette HTML event.                
class MyHTMLEventHandler(adsk.core.HTMLEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            htmlArgs = adsk.core.HTMLEventArgs.cast(args)
            data = json.loads(htmlArgs.data)
            if htmlArgs.action == 'ready':
                print('HTML ready')

                # Cannot do sendInfoToHTML inside the event handler. We either have to use htmlArgs.returnData or
                # spawn a thread (does not seem very safe? Can we call into the event loop instead?).
                invalidate(htmlArgs)
        except:
            ui.messageBox('Vertical Timeline failed:\n{}'.format(traceback.format_exc()))   

class CommandTerminationReason:
    UnknownTerminationReason = 0
    CompletedTerminationReason = 1
    CancelledTerminationReason = 2
    AbortedTerminationReason = 3
    PreEmptedTerminationReason = 4
    SessionEndingTerminationReason = 5

class CommandTerminatedHandler(adsk.core.ApplicationCommandEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            eventArgs = adsk.core.ApplicationCommandEventArgs.cast(args)
            
            # As long as we don't update on command create, we only need to listen for command completion
            if eventArgs.terminationReason != CommandTerminationReason.CompletedTerminationReason:
                return

            # Heavy traffic commands
            if eventArgs.commandId in ['SelectCommand', 'CommitCommand']:
                return
            
            invalidate()
        except:
            ui.messageBox('Vertical Timeline failed:\n{}'.format(traceback.format_exc()))

# global set of event handlers to keep them referenced for the duration of the command
handlers = []
ui = None
app = None
onCommandTerminated = None

def run(context):
    global ui, app, handlers
    debug = False
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface

         # Add a command that displays the panel.
        showPaletteCmdDef = ui.commandDefinitions.itemById('thomasa88-showVerticalTimeline')

        if not showPaletteCmdDef:
            showPaletteCmdDef = ui.commandDefinitions.addButtonDefinition('thomasa88-showVerticalTimeline',
                                                                           'Show Vertical Timeline',
                                                                           'Show Vertical', '')

            # Connect to Command Created event.
            onCommandCreated = ShowPaletteCommandCreatedHandler()
            showPaletteCmdDef.commandCreated.add(onCommandCreated)
            handlers.append(onCommandCreated)
        
        # Add the command to the toolbar.
        panel = ui.allToolbarPanels.itemById('SolidScriptsAddinsPanel')
        cntrl = panel.controls.itemById('thomasa88-showVerticalTimeline')
        if not cntrl:
            panel.controls.addCommand(showPaletteCmdDef)

        global onCommandTerminated
        onCommandTerminated = CommandTerminatedHandler()
        ui.commandTerminated.add(onCommandTerminated)
        handlers.append(onCommandTerminated)

        print("Running")
    except:
        print('Vertical Timeline failed:\n{}'.format(traceback.format_exc()))
        if ui and not debug:
            ui.messageBox('Vertical Timeline failed:\n{}'.format(traceback.format_exc()))

def stop(context):
    try:
        print('Stopping')

        # Do we need to remove the commandTerminated handler or not?
        if onCommandTerminated:
            ui.commandTerminated.remove(onCommandTerminated)

        # Delete the palette created by this add-in.
        palette = ui.palettes.itemById('thomasa88-verticalTimelinePalette')
        if palette:
            palette.deleteMe()

        # Delete controls and associated command definitions created by this add-ins
        panel = ui.allToolbarPanels.itemById('SolidScriptsAddinsPanel')
        cmd = panel.controls.itemById('thomasa88-showVerticalTimeline')
        if cmd:
            cmd.deleteMe()
        cmdDef = ui.commandDefinitions.itemById('thomasa88-showVerticalTimeline')
        if cmdDef:
            cmdDef.deleteMe()
    except:
        if ui:
            ui.messageBox('Vertical Timeline failed:\n{}'.format(traceback.format_exc()))

def get_timeline():
    product = app.activeProduct
    design = adsk.fusion.Design.cast(product)

    try:
        return design.timeline
    except RuntimeError:
        # Not parametric design (?)
        return None

FEATURE_MAP = {
    'LoftFeature': lambda e: 'solid/loft' if e.isSolid else 'surface/loft',
    'Sketch': 'sketch/Sketch_feature',
    'ExtrudeFeature': lambda e: 'solid/extrude' if e.isSolid else 'surface/extrude',
    'Occurrence': 'Modeling/BooleanNewComponent',
    'BoundaryFillFeature': 'surface/surface_sculpt',
    'SurfaceDeleteFaceFeature': 'modify/surface_delete',
    'CombineFeature': 'modify/combine'
}

def get_feature_image(entity):
    fusionType = entity.classType().replace('adsk::fusion::', '')
    match = FEATURE_MAP.get(fusionType)
    if callable(match):
        match = match(entity)

    if not match:
        # Image not mapped
        match = 'finish/finishX'
    
    return get_image_path(match)

def get_image_path(subpath):
    path = f'{get_resource_folder()}/{subpath}/16x16.png'
    if os.path.exists(path):
        return path
    else:
        print(f'File does not exist: {path}')
        return None

_resFolder = None
def get_resource_folder():
    global _resFolder
    if not _resFolder:
        _resFolder = ui.workspaces.itemById('FusionSolidEnvironment').resourceFolder.replace('/Environment/Model', '')
    return _resFolder

def find_commands(substring):
    return [c.id for c in ui.commandDefinitions if substring in c.id.lower()]

def find_commands_by_resource_folder(folder):
    commands = []
    for c in ui.commandDefinitions:
        try:
            if folder in c.resourceFolder.lower():
                commands.append(c.id)
        except:
            pass
    return commands

# ui.commandDefinitions.itemById('').resourceFolder
# design.rootComponent.allOccurrences[0].component.sketches

def invalidate(toHtmlArgsReturn=None):
    palette = ui.palettes.itemById('thomasa88-verticalTimelinePalette')

    timeline = get_timeline()

    features = get_features(timeline)

    action = 'setTimeline'
    data = features
    if toHtmlArgsReturn:
        # Cannot do sendInfoToHTML inside the HTML event handler. We either have to use htmlArgs.returnData or
        # spawn a thread (does not seem very safe? Can we call into the event loop instead?).
        html_command = {'action': 'setTimeline', 'data': data}
        html_commands = [html_command]
        toHtmlArgsReturn.returnData = json.dumps(html_commands) 
    else:
        palette.sendInfoToHTML('setTimeline', json.dumps(data))

def get_features(timeline_container):
    features = []
    for item in timeline_container:
        classType = item.classType()
        feature = {
            'name': item.name,
            'suppressed': item.isSuppressed,
            }
        if classType == 'adsk::fusion::TimelineObject':
            feature['type'] = item.entity.classType().split('::')[-1],
            feature['image'] = get_feature_image(item.entity)
        elif classType == 'adsk::fusion::TimelineGroup':
            feature['type'] = 'GROUP'
            feature['image'] = get_image_path('Timeline/GroupFeature')
            feature['children'] = get_features(item)
        else:
            print("Unhandled timeline item:", classType)
            continue
        features.append(feature)
    return features