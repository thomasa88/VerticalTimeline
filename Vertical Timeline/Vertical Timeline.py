#Author-Thomas Axelsson
#Description-Provides a vertical timeline.

import adsk.core, adsk.fusion, adsk.cam, traceback

import json
import os

# global set of event handlers to keep them referenced for the duration of the command
handlers = []
ui = None
app = None
onCommandTerminated = None

# Occurrence types
OCCURRENCE_GENERAL_COMP = 0
OCCURRENCE_COPY_COMP = 1
OCCURRENCE_SHEET_METAL = 2
OCCURRENCE_BODIES_COMP = 3

def get_timeline():
    product = app.activeProduct
    design = adsk.fusion.Design.cast(product)

    try:
        return design.timeline
    except RuntimeError:
        # Not parametric design (?)
        return None

def get_occurrence_type(item):
    if item.name.startswith('CopyPaste '):
        return OCCURRENCE_COPY_COMP
    elif hasattr(item.entity, 'bRepBodies'):
        if item.entity.bRepBodies.count == 0:
            return OCCURRENCE_SHEET_METAL
        else:
            return OCCURRENCE_BODIES_COMP
    else:
        return OCCURRENCE_GENERAL_COMP

OCCURRENCE_RESOURCE_MAP = {
    OCCURRENCE_GENERAL_COMP: 'Fusion/UI/FusionUI/Resources/Modeling/BooleanNewComponent',
    OCCURRENCE_COPY_COMP: 'Fusion/UI/FusionUI/Resources/Assembly/CopyPasteInstance',
    OCCURRENCE_SHEET_METAL: 'Neutron/UI/Base/Resources/Browser/ComponentSheetMetal',
    OCCURRENCE_BODIES_COMP: 'Fusion/UI/FusionUI/Resources/Assembly/CreateComponentFromBody',
}

FEATURE_RESOURCE_MAP = {
    # This list is hand-crafted. Please respect the work put into this list and
    # retain the Copyright and License stanzas if you copy it.
    # Helpful toosl: ImageSorter, Process Monitor.
    'LoftFeature': lambda i: 'Fusion/UI/FusionUI/Resources/solid/loft' if i.entity.isSolid else 'Fusion/UI/FusionUI/Resources/surface/loft',
    'Sketch': 'Fusion/UI/FusionUI/Resources/sketch/Sketch_feature',
    'ExtrudeFeature': lambda i: 'Fusion/UI/FusionUI/Resources/solid/extrude' if i.entity.isSolid else 'Fusion/UI/FusionUI/Resources/surface/extrude',
    'Occurrence': lambda i: OCCURRENCE_RESOURCE_MAP[get_occurrence_type(i)],
    'BoundaryFillFeature': 'Fusion/UI/FusionUI/Resources/surface/surface_sculpt',
    'SurfaceDeleteFaceFeature': 'Fusion/UI/FusionUI/Resources/modify/surface_delete',
    'CombineFeature': 'Fusion/UI/FusionUI/Resources/modify/combine',
    'RevolveFeature': lambda i: 'Fusion/UI/FusionUI/Resources/solid/revolve' if i.entity.isSolid else 'Fusion/UI/FusionUI/Resources/surface/revolve',
    'SweepFeature': lambda i: 'Fusion/UI/FusionUI/Resources/solid/sweep' if i.entity.isSolid else 'Fusion/UI/FusionUI/Resources/surface/sweep',
    'RibFeature': lambda i: 'Fusion/UI/FusionUI/Resources/solid/rib',
    'WebFeature': lambda i: 'Fusion/UI/FusionUI/Resources/solid/web',
    'BoxFeature': lambda i: 'Fusion/UI/FusionUI/Resources/solid/primitive_box',
    'CylinderFeature': 'Fusion/UI/FusionUI/Resources/solid/primitive_cylinder',
    'SphereFeature': 'Fusion/UI/FusionUI/Resources/solid/primitive_sphere',
    'TorusFeature': 'Fusion/UI/FusionUI/Resources/solid/primitive_torus',
    'CoilFeature': 'Fusion/UI/FusionUI/Resources/solid/Coil',
    'PipeFeature': 'Fusion/UI/FusionUI/Resources/solid/primitive_pipe',
    'RectangularPatternFeature': 'Fusion/UI/FusionUI/Resources/pattern/pattern_rectangular',
    'CircularPatternFeature': 'Fusion/UI/FusionUI/Resources/pattern/pattern_circular',
    'PathPatternFeature': 'Fusion/UI/FusionUI/Resources/pattern/pattern_path',
    'MirrorFeature': 'Fusion/UI/FusionUI/Resources/pattern/pattern_mirror',
    'ThickenFeature': 'Fusion/UI/FusionUI/Resources/surface/thicken',
}

def get_feature_image(item):
    entity = item.entity
    fusionType = entity.classType().replace('adsk::fusion::', '')
    match = FEATURE_RESOURCE_MAP.get(fusionType)
    if callable(match):
        match = match(item)

    if not match:
        # Image not mapped
        match = 'Fusion/UI/FusionUI/Resources/finish/finishX'
    
    return get_image_path(match)

def get_image_path(subpath):
    path = f'{get_product_deploy_folder()}/{subpath}/16x16.png'
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

def get_product_deploy_folder():
    return get_resource_folder().replace('/Fusion/UI/FusionUI/Resources', '')

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

timeline_cache = []
def invalidate(send=True):
    global timeline_cache

    palette = ui.palettes.itemById('thomasa88_verticalTimelinePalette')

    if not palette:
        print("Should not try to invalidate when the palette is not shown.")
        return

    timeline = get_timeline()
    features = get_features(timeline)
    timeline_cache = features

    action = 'setTimeline'
    data = features
    if not send:
        # Cannot do sendInfoToHTML inside the HTML event handler. We either have to use htmlArgs.returnData or
        # spawn a thread (does not seem very safe? Can we call into the event loop instead?).
        html_command = {'action': 'setTimeline', 'data': data}
        return html_command
    else:
        palette.sendInfoToHTML('setTimeline', json.dumps(data))

def get_features(timeline_container, id_base=''):
    features = []
    for i, item in enumerate(timeline_container):
        classType = item.classType()
        feature = {
            'id': f'{id_base}{i}',
            'name': item.name,
            'suppressed': item.isSuppressed or item.isRolledBack,
            }
        if not item.isGroup:
            feature['type'] = item.entity.classType().split('::')[-1]
            feature['image'] = get_feature_image(item)

            if feature['type'] == 'Occurrence':
                # Fusion uses a space separator for the timeline object name, but sometimes the first part is empty.
                # Strip the whitespace to make the list cleaner.
                feature['name'] = feature['name'].lstrip()
                if get_occurrence_type(item) != OCCURRENCE_BODIES_COMP:
                    # Name is a read-only instance variant of the component's name
                    # Let the user modify the component's name instead
                    feature['component-name'] = item.entity.component.name
        else:
            feature['type'] = 'GROUP'
            feature['image'] = get_image_path('Fusion/UI/FusionUI/Resources/Timeline/GroupFeature')
            feature['children'] = get_features(item, feature['id'] + '-')
        features.append(feature)
    return features

def get_item_by_id_string(id_string):
    item = get_timeline()
    for i in id_string:
        item = item[int(i)]
    return item

def run(context):
    global ui, app, handlers
    debug = False
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface

         # Add a command that displays the panel.
        showPaletteCmdDef = ui.commandDefinitions.itemById('thomasa88_showVerticalTimeline')

        if not showPaletteCmdDef:
            showPaletteCmdDef = ui.commandDefinitions.addButtonDefinition(
                'thomasa88_showVerticalTimeline',
                'Show Vertical Timeline',
                'Vertical Timeline\n\n' +
                'A vertical timeline, that shows feature names. Timeline functionality is limited.',
                '')

            # Connect to Command Created event.
            onCommandCreated = ShowPaletteCommandCreatedHandler()
            showPaletteCmdDef.commandCreated.add(onCommandCreated)
            handlers.append(onCommandCreated)
        
        # Add the command to the toolbar.
        panel = ui.allToolbarPanels.itemById('SolidScriptsAddinsPanel')
        cntrl = panel.controls.itemById('thomasa88_showVerticalTimeline')
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
        palette = ui.palettes.itemById('thomasa88_verticalTimelinePalette')
        if palette:
            palette.deleteMe()

        # Delete controls and associated command definitions created by this add-ins
        panel = ui.allToolbarPanels.itemById('SolidScriptsAddinsPanel')
        cmd = panel.controls.itemById('thomasa88_showVerticalTimeline')
        if cmd:
            cmd.deleteMe()
        cmdDef = ui.commandDefinitions.itemById('thomasa88_showVerticalTimeline')
        if cmdDef:
            cmdDef.deleteMe()
    except:
        if ui:
            ui.messageBox('Vertical Timeline failed:\n{}'.format(traceback.format_exc()))


# Event handler for the commandExecuted event.
class ShowPaletteCommandExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            # Create and display the palette.
            palette = ui.palettes.itemById('thomasa88_verticalTimelinePalette')
            if not palette:
                palette = ui.palettes.add('thomasa88_verticalTimelinePalette', 'Vertical Timeline', 'palette.html',
                                          True, True, True, 250, 500, False)
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
            action = htmlArgs.action
            data = json.loads(htmlArgs.data)
            html_commands = []
            if action == 'ready':
                print('HTML ready')

                # Cannot do sendInfoToHTML inside the event handler. We either have to use htmlArgs.returnData or
                # spawn a thread (does not seem very safe? Can we call into the event loop instead?).
                html_commands.append(invalidate(send=False))
            elif action == 'setFeatureName':
                item = get_item_by_id_string(data['id'].split('-'))
                if (not item.isGroup
                    and item.entity.classType() == 'adsk::fusion::Occurrence'
                    and get_occurrence_type(item) != OCCURRENCE_BODIES_COMP):
                    item.entity.component.name = data['value']
                    html_commands.append(True)
                    html_commands.append(invalidate(send=False))
                else:
                    item.name = data['value']
                    html_commands.append(True)
            elif action == 'selectFeature':
                ret = True
                item = get_item_by_id_string(data['id'].split('-'))

                if item.isSuppressed:
                    ui.messageBox('Cannot select suppressed features')
                    ret = False
                elif item.isRolledBack:
                    ui.messageBox('Cannot select rolled back features')
                    ret = False
                else:
                    # Making this in a transactory way so the current selection is not removed
                    # if the entity is not selectable.
                    newSelection = adsk.core.ObjectCollection.create()
                    newSelection.add(item.entity)
                    try:
                        ui.activeSelections.all = newSelection
                    except:
                        ui.messageBox('Cannot select this entity')
                        ret = False
                html_commands.append(ret)
            if html_commands:
                htmlArgs.returnData = json.dumps(html_commands)
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

